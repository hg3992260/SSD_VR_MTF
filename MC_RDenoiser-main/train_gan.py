from argprase import parse_args
import os
import yaml
import losses
import torch.backends.cudnn as cudnn
import models as models
import torch.optim as optim
from glob import glob
import albumentations as albu
from sklearn.model_selection import train_test_split
import datasets
from datasets import DataSetTrain,DataSetVal
import torch
from collections import OrderedDict
from tools.utils import AverageMeter
from tqdm import tqdm
import pandas as pd
import numpy as np
import time
from skimage.metrics import structural_similarity
from skimage.metrics import peak_signal_noise_ratio
import cv2
from volumn_data import prepare
LOSS_NAMES = losses.__all__
MODEL_NAMES = models.__all__
from apex import amp
import torch.nn.functional as F

eps = 0.00316
def BMFRGammaCorrection(img):
    if isinstance(img, np.ndarray):
        return np.clip(np.power(np.maximum(img, 0.0), 0.454545), 0.0, 1.0)
    elif isinstance(img, torch.Tensor):
        return torch.pow(torch.clamp(img, min=0.0, max=1.0), 0.454545)
def ComputeMetrics(truth_img, test_img):
    truth_img = BMFRGammaCorrection(truth_img)
    test_img  = BMFRGammaCorrection(test_img)

    SSIM = structural_similarity(truth_img, test_img, multichannel=True)
    PSNR = peak_signal_noise_ratio(truth_img, test_img)
    return SSIM, PSNR




# 没用kd
def train(train_loader, networkG,networkD, criterion, optimizerG,optimizerD):
    avg_meters = {'loss': AverageMeter()}
    networkG.train()


    pbar = tqdm(total=len(train_loader))
    for (features, target) in train_loader:

        # 写在前面吧，写在这里浪费时间
        sdf = features[:, 0:3, :, :]
        illu = features[:, 3:6, :, :]

        target = target.cuda()
        sdf = sdf.cuda()
        illu = illu.cuda()
        outputs = networkG(sdf, illu)
        # train discriminator
        networkD.train()
        optimizerD.zero_grad()
        C_real = networkD(target)
        C_fake = networkD(torch.clamp(outputs.detach(), 0, 1))
        mean_C_real = torch.mean(C_real, dim=(0,), keepdim=True).expand_as(C_real).detach()
        mean_C_fake = torch.mean(C_fake, dim=(0,), keepdim=True).expand_as(C_fake).detach()
        loss1 = F.mse_loss(C_real - mean_C_fake, torch.tensor(1.0).cuda().expand_as(C_real))
        loss2 = F.mse_loss(C_fake - mean_C_real, torch.tensor(-1.0).cuda().expand_as(C_fake))
        lossDD = 0.5 * (loss1 + loss2)
        lossDD.backward()
        # clip: value for gradient norm clipping default=1
        torch.nn.utils.clip_grad_value_(networkD.parameters(), 1)
        torch.nn.utils.clip_grad_norm_(networkD.parameters(), 1)
        optimizerD.step()

        # train generator
        networkD.eval()
        optimizerG.zero_grad()
        C_real = networkD(target)
        C_fake = networkD(torch.clamp(outputs, 0, 1))
        mean_C_real = torch.mean(C_real, dim=(0,), keepdim=True).expand_as(C_real).detach()
        mean_C_fake = torch.mean(C_fake, dim=(0,), keepdim=True).expand_as(C_fake).detach()
        loss1 = F.mse_loss(C_fake - mean_C_real, torch.tensor(1.0).cuda().expand_as(C_fake))
        loss2 = F.mse_loss(C_real - mean_C_fake, torch.tensor(-1.0).cuda().expand_as(C_real))
        lossDG = 0.5 * (loss1 + loss2)
        lossR = criterion(outputs, target)
        # loss = (2 * lossDG * lossR) / (lossDG + lossR)
        loss = 0.6 * lossDG + 0.4 * lossR
        loss.backward()
        torch.nn.utils.clip_grad_value_(networkG.parameters(), 1)
        torch.nn.utils.clip_grad_norm_(networkG.parameters(), 1)
        optimizerG.step()

        avg_meters['loss'].update(loss.item(), sdf.size(0))
        postfix = OrderedDict([('loss', avg_meters['loss'].avg),])
        pbar.set_postfix(postfix)
        pbar.update(1)
        # 释放未使用的内存
        # torch.cuda.empty_cache()

    pbar.close()

    return OrderedDict([('loss', avg_meters['loss'].avg),])



# val里没有loss回传
def validate(val_loader, networkG, criterion):

    flag = 1
    avg_meters = {'loss': AverageMeter(),}
    networkG.eval()
    SSIMs = []
    PSNRs = []

    with torch.no_grad():
        pbar = tqdm(total=len(val_loader))
        for features, target in val_loader:
            sdf = features[:, 0:3, :, :]
            illu = features[:, 3:6, :, :]

            target = target.cuda()
            sdf = sdf.cuda()
            illu = illu.cuda()
            # print(1)
            # compute output
            outputs = networkG(sdf,illu)
            # print(2)
            loss = criterion(outputs, target)
            output = outputs
            # evaluate
            if flag == 1:
                flag = 0
                # input_ = input.cpu().numpy()
                output = output.cpu().numpy()
                target = target.cpu().numpy()

                for i in range(output.shape[0]):
                    if np.sum(target[i]) == 0.0:
                        continue
                    curr_target = target[i].transpose((1, 2, 0))
                    curr_out = output[i].transpose((1, 2, 0))

                    # curr_input = input_[i].transpose((1, 2, 0))

                    # input_ = prepare(curr_input)
                    curr_out = prepare(curr_out)
                    curr_target = prepare(curr_target)
                    # input,ref,output全部进行颜色映射

                    # output = np.concatenate((input_, curr_target), axis=1)
                    curr_target = np.concatenate((curr_out, curr_target), axis=1)
                    # curr_target = cv2.cvtColor(curr_target * 255, cv2.COLOR_RGB2BGR)
                    curr_target = curr_target * 255
                    cv2.imwrite("./log/output{}.png".format(i), curr_target)

            avg_meters['loss'].update(loss.item(),sdf.size(0))

            postfix = OrderedDict([
                ('loss', avg_meters['loss'].avg),
            ])
            pbar.set_postfix(postfix)
            pbar.update(1)
        pbar.close()

    return OrderedDict([('loss', avg_meters['loss'].avg),])

def main():
    save_path = 'D:\\DataSets\\models\\RDnet\\'
    # -------- parameter ---------
    use_val = True
    config = vars(parse_args())

    print('-' * 20)
    for key in config:
        print('%s: %s' % (key, config[key]))
    print('-' * 20)
    os.makedirs('{}{}'.format(save_path, config['name']), exist_ok=True)

    with open('{}{}//config.yml'.format(save_path,config['name']), 'w') as f:
        yaml.dump(config, f)

    # -------- load model --------
    criterion = losses.__dict__["MS_SSIM_L1_LOSS"]().cuda()
    cudnn.benchmark = True
    # 创建模型实例
    device = torch.device("cuda")
    # model = torch.load('{}{}//model.pt'.format(save_path, config['testname']), map_location=device)
    modelG = models.__dict__["Teacher_Model"]()
    # student_net_sdf.load_state_dict(torch.load('models_sdf/1-manix-2spp/model.pth'))
    modelG = modelG.cuda()
    modelD = models.__dict__["Discriminator"]()
    modelD = modelD.cuda()
    # params = filter(lambda p: p.requires_grad, model.parameters())
    # 不设置正则化，weightdecay默认为0，设置betas表示动量
    optimizerG = optim.Adam(modelG.parameters(), lr=config['lr'], betas=(0.9, 0.999))
    optimizerD = optim.Adam(modelD.parameters(), lr=config['lr'], betas=(0.9, 0.999))
    # loss_fn = losses.L1SpecLoss()


    # -------- load dataset --------

    train_dataset = DataSetTrain(
        img_dir=os.path.join(config['trainpath'], config['dataset'], config['noisetype']),
        ref_dir=os.path.join(config['trainpath'], config['dataset'], config['reftype']),
        # transform=train_transform
    )
    val_dataset = DataSetVal(

        img_dir=os.path.join(config['valpath'],config['dataset'],config['noisetype']),
        ref_dir=os.path.join(config['valpath'],config['dataset'],config['reftype']),
        # transform=val_transform
    )

    def seed_fn(id):
        np.random.seed()
    # worker_init_fn 能显著提高数据集读取速度
    # pin_memory 当设置为True时，它告诉DataLoader将加载的数据张量固定在CPU内存中，而不是GPU内存中。这样做的目的是使数据传输到GPU的过程更快，因为在GPU训练期间，数据不需要从CPU内存复制到GPU内存。
    train_loader = torch.utils.data.DataLoader(
        train_dataset,
        batch_size=config['batch_size'],
        shuffle=True,
        num_workers=config['num_workers'],
        drop_last=True,
        worker_init_fn = seed_fn,
        pin_memory=True
    )
    val_loader = torch.utils.data.DataLoader(
        val_dataset,
        # batch_size=config['batch_size'],
        batch_size=max(1, torch.cuda.device_count()),
        shuffle=False,
        num_workers=config['num_workers'],
        drop_last=True,
        worker_init_fn=seed_fn,
        pin_memory=True
    )
    log = OrderedDict([
        ('epoch', []),
        ('lr', []),
        ('loss', []),
        ('val_loss', []),
    ])
    min_loss = 10

    # 多加入一个并行机制，当有多个gpu的时候可以用
    parallel_modelG = torch.nn.DataParallel(modelG)
    parallel_modelD = torch.nn.DataParallel(modelD)

    # train sdf
    for epoch in range(config['epochs']):
        print('Epoch [%d/%d]' % (epoch, config['epochs']))

        # train for one epoch
        train_log = train(train_loader, parallel_modelG,parallel_modelD, criterion, optimizerG,optimizerD)
        val_log = validate(val_loader, parallel_modelG, criterion)

        print('loss %.4f '% (train_log['loss']))
        log['epoch'].append(epoch)
        log['lr'].append(config['lr'])
        log['loss'].append(train_log['loss'])
        log['val_loss'].append(val_log['loss'])
        pd.DataFrame(log).to_csv('{}{}\\log.csv'.format(save_path,config['name']), index=False)
        if val_log['loss'] < min_loss:
            min_loss = val_log['loss']
            # checkpoint = {
            #     'best_loss': min_loss,
            #     'weights': modelG.state_dict(),
            #     'optimizer': optimizerG.state_dict(),
            # }
            torch.save(modelG,'{}{}\\Generator.pt'.format(save_path,config['name']))
            torch.save(modelD, '{}{}\\Discriminator.pt'.format(save_path, config['name']))
            # torch.save(model.state_dict(), 'models_sdf/%s/model.pth' % config['name'])

            print("=> saved best model")
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()

