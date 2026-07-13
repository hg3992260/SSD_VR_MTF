from argprase import parse_args
import os
import yaml
import losses
import torch.backends.cudnn as cudnn
import models as models
import torch.optim as optim
from tools.prepare_data import *
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
def train(train_loader, network, criterion, optimizer):
    avg_meters = {'loss': AverageMeter()}
    network.train()

    pbar = tqdm(total=len(train_loader))
    for (features, target) in train_loader:

        # 写在前面吧，写在这里浪费时间
        sdf = features[:, 0:3, :, :]
        illu = features[:, 3:6, :, :]

        target = target.cuda()
        sdf = sdf.cuda()
        illu = illu.cuda()

        # compute output
        optimizer.zero_grad()
        outputs = network(sdf,illu)

        loss = criterion(outputs, target)

        avg_meters['loss'].update(loss.item(), sdf.size(0))

        # compute gradient and do optimizing step

        loss.backward()
        torch.nn.utils.clip_grad_value_(network.parameters(),1)
        torch.nn.utils.clip_grad_norm_(network.parameters(), 1)

        optimizer.step()

        postfix = OrderedDict([('loss', avg_meters['loss'].avg),])
        pbar.set_postfix(postfix)
        pbar.update(1)
        # 释放未使用的内存
        # torch.cuda.empty_cache()

    pbar.close()

    return OrderedDict([('loss', avg_meters['loss'].avg),])



# val里没有loss回传
def validate(val_loader, network, criterion,use_val):
    if use_val == False:
        return
    flag = 1
    avg_meters = {'loss': AverageMeter(),}
    network.eval()
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

            # compute output
            outputs = network(sdf,illu)

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
                    writeimage(output[i],"./log/output.png")
                    writeimage(target[i], "./log/ref.png")

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
    criterion = losses.__dict__["CombinedLoss"]().cuda()
    cudnn.benchmark = True
    # 创建模型实例
    device = torch.device("cuda")
    # model = torch.load('{}{}//model.pt'.format(save_path, config['testname']), map_location=device)
    model = models.__dict__["Single_Model"]()
    # student_net_sdf.load_state_dict(torch.load('models_sdf/1-manix-2spp/model.pth'))
    model = model.cuda()
    # params = filter(lambda p: p.requires_grad, model.parameters())
    # 不设置正则化，weightdecay默认为0，设置betas表示动量
    optimizer = optim.Adam(model.parameters(), lr=config['lr'], betas=(0.9, 0.999))


    # 用初始化混合精度训练工具Apex，能够在不降低性能的情况下，将模型训练的速度提升2-4倍，训练显存消耗减少为之前的一半
    # 用起来似乎不太正常，loss不下降
    # model, optimizer = amp.initialize(model, optimizer, opt_level="O2")

    # 加入一个学习率调度器
    # patience：连续25轮没有改善就降低学习率 cooldown继续检查间隔的轮数，factor下调百分比 minlr最低学习率
    # scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=25, cooldown=10, factor=0.5, min_lr=1e-5,
    #                                                        threshold=1e-5)

    # -------- load dataset --------

    # img_ids = glob(os.path.join(config['datapath'],config['dataset'],config['noisetype'],"*.exr"))
    # img_ids = [os.path.splitext(os.path.basename(p))[0] for p in img_ids]

    # random_state每次设置同样的值时，train和val的数据集是一样的！不要设置成一样
    # train_img_ids, val_img_ids = train_test_split(img_ids, test_size=0.2)
    # train_transform = albu.Compose([
    #     # adjust w and h
    #     albu.Resize(height=2048, width=2048, interpolation=1),
    #   albu.CenterCrop(1024,1024),
    # ])
    # val_transform = albu.Compose([
    #    # albu.Resize(height=2048, width=2048, interpolation=1),
    #     albu.CenterCrop(1024, 1024),
    #     # albu.Resize(config['input_h'], config['input_w']),
    # ])
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
    parallel_model = torch.nn.DataParallel(model)

    # train sdf
    for epoch in range(config['epochs']):
        print('Epoch [%d/%d]' % (epoch, config['epochs']))

        # train for one epoch
        train_log = train(train_loader, parallel_model, criterion, optimizer)
        val_log = validate(val_loader, parallel_model,  criterion, use_val)

        print('loss %.4f '% (train_log['loss']))
        log['epoch'].append(epoch)
        log['lr'].append(config['lr'])
        log['loss'].append(train_log['loss'])
        log['val_loss'].append(val_log['loss'])
        pd.DataFrame(log).to_csv('{}{}\\log.csv'.format(save_path,config['name']), index=False)
        if val_log['loss'] < min_loss:
            min_loss = val_log['loss']
            checkpoint = {
                'best_loss': min_loss,
                'weights': model.state_dict(),
                'optimizer': optimizer.state_dict(),
            }
            torch.save(model,'{}{}\\model.pt'.format(save_path,config['name']))
            # torch.save(model.state_dict(), 'models_sdf/%s/model.pth' % config['name'])

            print("=> saved best model")
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()

