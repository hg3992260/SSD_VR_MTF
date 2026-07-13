import models
from argprase import *
from torch.autograd import Variable
import yaml
import torch
import onnxruntime
import cv2
from skimage.transform import resize
import torchvision.transforms as transforms
from PIL import Image
from tools.prepare_data import get_sdf,get_illu
import numpy as np
import time
def prepare(img):

    exposure = 0.9
    invExposure = 1.0 / (1.0 - exposure)
    gamma = 2.2
    img = 1.0 - np.exp(-img * invExposure)

    return img
# 保存onnx模型
def save_onnx():
    input_name = ['input']
    output_name = ['output']

    models_sdf = models.__dict__["Teacher_Model"]()
    models_sdf = models_sdf.cuda()

    args = parse_args()
    with open('models_sdf/%s/config.yml' % args.testname, 'r') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)

    models_sdf.load_state_dict(torch.load('models_sdf/%s/model.pth' %
                                          config['testname']))
    models_sdf.eval()
    input1 = Variable(torch.randn(1, 3, 1024, 1024)).cuda()
    input2 = Variable(torch.randn(1, 3, 1024, 1024)).cuda()
    torch.onnx.export(models_sdf, (input1, input2), 'models_sdf/%s/model.onnx' % config['testname'], input_names=['input1', 'input2'], output_names=output_name, verbose=False)

def to_numpy(tensor):
    return tensor.detach().cpu().numpy() if tensor.requires_grad else tensor.cpu().numpy()

# 自定义的数据增强



def onnx_predict():
    img_sdf,alpha = get_sdf("C://backup//RenderedImages//Data1//GBuffers.exr")
    img_illu = get_illu("C://backup//RenderedImages//Data1//GBuffers.exr")
    # print(img_sdf.shape)

    img_illu = np.concatenate((img_illu, img_sdf), axis=2)
    # img = img_sdf
    # 推理的图片路径
    # sdf处理
    print(img_illu.shape)
    img_illu = resize(img_illu, (1024, 1024,6), order=1)
    # img_illu = img_illu[0:1024, 0:1024, :]
    # img_sdf = img_sdf[0:1024, 0:1024, :]
    img_sdf = resize(img_sdf, (1024, 1024, 3), order=1)
    img_illu = img_illu.transpose(2, 0, 1)
    img_sdf = img_sdf.transpose(2, 0, 1)
    img_illu = img_illu.astype('float32')
    img_sdf = img_sdf.astype('float32')

    timg_illu = torch.from_numpy(img_illu)
    timg_sdf = torch.from_numpy(img_sdf)
    timg_illu = timg_illu.unsqueeze_(0)  # -> NCHW, 1,3,224,224
    timg_sdf = timg_sdf.unsqueeze_(0)
    onnx_model_path = "static_model\\manix_illu.onnx"
    onnx_model_path2 = "static_model\\manix_sdf.onnx"
    resnet_session_illu = onnxruntime.InferenceSession(onnx_model_path, providers=['TensorrtExecutionProvider'])
    resnet_session_sdf = onnxruntime.InferenceSession(onnx_model_path2, providers=['TensorrtExecutionProvider'])
    inputs_illu = {resnet_session_illu.get_inputs()[0].name: to_numpy(timg_illu)}
    inputs_sdf = {resnet_session_sdf.get_inputs()[0].name: to_numpy(timg_sdf)}
    # 模型加载 sdf
    for i in range(1):

        start = time.time()
        output_illu = resnet_session_illu.run(None, inputs_illu)[0]
        output_sdf = resnet_session_sdf.run(None, inputs_sdf)[0]
        end = time.time()
        print("load data time:%.5fs" % (end - start))
        # print("onnx weights", outs)
        # print("onnx prediction", outs.argmax(axis=1)[0])

        output_illu = output_illu[0].transpose((1, 2, 0))

        output_sdf = output_sdf[0].transpose((1, 2, 0))
        output = output_illu * output_sdf

        output = prepare(output)


        cv2.imwrite("./results/testres/yes2.png", output*255)


if __name__ == "__main__":
    save_onnx()
    # onnx_predict()
