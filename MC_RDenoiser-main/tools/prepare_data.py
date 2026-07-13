import OpenEXR
import Imath
import numpy as np
import re
import cv2
import os
from PIL import Image
from scipy.ndimage import gaussian_filter
def prepare(img):

    exposure = 0.8
    invExposure = 1.0 / (1.0 - exposure)
    gamma = 2.2
    img = 1.0 - np.exp(-img * invExposure)

    return img

def arr2np(arr):
    channels = len(arr)
    height, width = arr[0].shape
    x = np.zeros((height, width, channels))
    for c in range(channels):
        x[:, :, c] = arr[c]
    x = np.abs(x) ** 0.5
    x = np.clip(x,0,1)
    return x

eps = 0.00316
def divide(d_rgb,d_albedo):
    # contains_zero = np.any(d_albedo == 0)
    # if contains_zero:
    #     print("数组中包含零")
    # else:
    #     print("数组中不包含零")
    # d_albedo对应位置= 0时，结果也为0
    # out = np.where(d_albedo == 0, 0, np.divide(d_rgb, d_albedo))
    # 对应位置<0.001时，结果为0
    out = np.where(d_albedo < 0.001, 0, np.divide(d_rgb, d_albedo))
    # 这段的意思是，只有d_albedo对应位置！ = 0时，才会将两者相除
   # out = np.divide(d_rgb,d_albedo,out=d_albedo,where=d_albedo != 0)

    # out = np.divide(d_rgb, d_albedo , out=d_rgb)
    return out


def get_illu(filename):
    # 只需要6个通道：illu_B,illu_G,ill_R,"Sdf_B","Sdf_G","Sdf_R"
    # 每个通道要除以alpha，如果alpha=0不用除

    exr_file = OpenEXR.InputFile(filename)
    header = exr_file.header()

    channel_names = ["Alpha", "SingleRadiDividedBySdf_B", "SingleRadiDividedBySdf_G", "SingleRadiDividedBySdf_R"]
    channel_datas = []
    for channelname in channel_names:
        half_channel = exr_file.channel(channelname, Imath.PixelType(Imath.PixelType.HALF))
        width = header['dataWindow'].max.x - header['dataWindow'].min.x + 1
        height = header['dataWindow'].max.y - header['dataWindow'].min.y + 1
        half_array = np.frombuffer(half_channel, dtype=np.float16)
        half_array = np.reshape(half_array, (height, width))

        channel_datas.append(half_array)
    channel_datas = np.array(channel_datas)

    I_appro = np.stack((channel_datas[1], channel_datas[2], channel_datas[3]), axis=2)
    # Radi = np.stack((channel_datas[4], channel_datas[5], channel_datas[6]), axis=2)
    # Alpha = np.stack((channel_datas[0], channel_datas[0], channel_datas[0]), axis=2)



    # Illu_appro = Illu_appro*Alpha
    # Illu_noalpha = divide(Illu, Alpha)
    # output = np.stack((Sdf_noalpha, Illumin_noalpha), axis=2)
    return I_appro



def get_sdf(filename):
    # 只需要6个通道：illu_B,illu_G,ill_R,"Sdf_B","Sdf_G","Sdf_R"
    # 每个通道要除以alpha，如果alpha=0不用除

    exr_file = OpenEXR.InputFile(filename)
    header = exr_file.header()

    channel_names = ["Alpha", "Sdf_B", "Sdf_G", "Sdf_R"]
    channel_datas = []
    for channelname in channel_names:
        half_channel = exr_file.channel(channelname, Imath.PixelType(Imath.PixelType.HALF))
        width = header['dataWindow'].max.x - header['dataWindow'].min.x + 1
        height = header['dataWindow'].max.y - header['dataWindow'].min.y + 1
        half_array = np.frombuffer(half_channel, dtype=np.float16)
        half_array = np.reshape(half_array, (height, width))

        channel_datas.append(half_array)
    channel_datas = np.array(channel_datas)

    Sdf = np.stack((channel_datas[1], channel_datas[2], channel_datas[3]), axis=2)
    # Alpha = np.stack((channel_datas[0], channel_datas[0], channel_datas[0]), axis=2)

    # output = np.stack((Sdf_noalpha, Illumin_noalpha), axis=2)
    return Sdf
# 直接得到radiance no alpha data
def get_volumn_radiance(filename):
    # 只需要6个通道：illu_B,illu_G,ill_R,"Sdf_B","Sdf_G","Sdf_R"
    # 每个通道要除以alpha，如果alpha=0不用除

    exr_file = OpenEXR.InputFile(filename)
    header = exr_file.header()

    channel_names = ["SingleRadi_B", "SingleRadi_G", "SingleRadi_R"]
    channel_datas = []
    for channelname in channel_names:
        half_channel = exr_file.channel(channelname, Imath.PixelType(Imath.PixelType.HALF))
        width = header['dataWindow'].max.x - header['dataWindow'].min.x + 1
        height = header['dataWindow'].max.y - header['dataWindow'].min.y + 1
        half_array = np.frombuffer(half_channel, dtype=np.float16)
        half_array = np.reshape(half_array, (height, width))

        channel_datas.append(half_array)
    channel_datas = np.array(channel_datas)

    Radiance = np.stack((channel_datas[0], channel_datas[1], channel_datas[2]), axis=2)
    # Alpha = np.stack((channel_datas[0], channel_datas[0], channel_datas[0]), axis=2)

    # Rad_noalpha = divide(Radiance, Alpha)

    # output = np.stack((Sdf_noalpha, Illumin_noalpha), axis=2)
    return Radiance

def get_volumn_radiancedalpha(filename):
    # 只需要6个通道：illu_B,illu_G,ill_R,"Sdf_B","Sdf_G","Sdf_R"
    # 每个通道要除以alpha，如果alpha=0不用除

    exr_file = OpenEXR.InputFile(filename)
    header = exr_file.header()

    channel_names = ["SingleRadi_B", "SingleRadi_G", "SingleRadi_R","Alpha"]
    channel_datas = []
    for channelname in channel_names:
        half_channel = exr_file.channel(channelname, Imath.PixelType(Imath.PixelType.HALF))
        width = header['dataWindow'].max.x - header['dataWindow'].min.x + 1
        height = header['dataWindow'].max.y - header['dataWindow'].min.y + 1
        half_array = np.frombuffer(half_channel, dtype=np.float16)
        half_array = np.reshape(half_array, (height, width))

        channel_datas.append(half_array)
    channel_datas = np.array(channel_datas)

    Radiance = np.stack((channel_datas[0], channel_datas[1], channel_datas[2]), axis=2)
    Alpha = np.stack((channel_datas[3], channel_datas[3], channel_datas[3]), axis=2)

    Rad_noalpha = divide(Radiance, Alpha)

    # output = np.stack((Sdf_noalpha, Illumin_noalpha), axis=2)
    return Rad_noalpha
def get_position(filename):
    # 只需要6个通道：illu_B,illu_G,ill_R,"Sdf_B","Sdf_G","Sdf_R"
    # 每个通道要除以alpha，如果alpha=0不用除

    exr_file = OpenEXR.InputFile(filename)
    header = exr_file.header()

    channel_names = ["Pos_X", "Pos_Y", "Pos_Z"]
    channel_datas = []
    for channelname in channel_names:
        half_channel = exr_file.channel(channelname, Imath.PixelType(Imath.PixelType.HALF))
        width = header['dataWindow'].max.x - header['dataWindow'].min.x + 1
        height = header['dataWindow'].max.y - header['dataWindow'].min.y + 1
        half_array = np.frombuffer(half_channel, dtype=np.float16)
        half_array = np.reshape(half_array, (height, width))

        channel_datas.append(half_array)
    channel_datas = np.array(channel_datas)

    Position = np.stack((channel_datas[0], channel_datas[1], channel_datas[2]), axis=2)
    # Alpha = np.stack((channel_datas[0], channel_datas[0], channel_datas[0]), axis=2)

    # Rad_noalpha = divide(Radiance, Alpha)

    # output = np.stack((Sdf_noalpha, Illumin_noalpha), axis=2)
    return Position
def arr2exr(arr, filename):
    # 创建一个示例的 NumPy 数组
    arr = arr.astype(np.float32)
    width,height,channel = arr.shape
    # 提取每个通道的数据
    radiance_b = arr[:, :, 0].tobytes()
    radiance_g = arr[:, :, 1].tobytes()
    radiance_r = arr[:, :, 2].tobytes()

    header = OpenEXR.Header(width, height)
    header['channels'] = {
        'radiance_b': Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT)),
        'radiance_g': Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT)),
        'radiance_r': Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT))
    }

    # 创建输出文件
    exr_file = OpenEXR.OutputFile(filename, header)

    # 定义通道名称和数据
    channels = {
        'radiance_b': radiance_r,
        'radiance_g': radiance_g,
        'radiance_r': radiance_b
    }

    # 保存数据到 EXR 文件
    exr_file.writePixels(channels)
    exr_file.close()


def natural_keys(text):
    """自定义键函数用于自然排序（使用os.path处理路径）"""
    # 使用os.path获取文件名
    basename = os.path.basename(text)
    # 返回数字列表以用于排序
    return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', basename)]


def clip(value, min_value, max_value):
    return max(min_value, min(value, max_value))


def fast_gauss_filter(src, radius):
    # 使用OpenCV的GaussianBlur实现快速高斯滤波
    return cv2.GaussianBlur(src, (0, 0), sigmaX=radius, sigmaY=radius)


def usm_sharpen(src, radius=3.1, amount=114, threshold=0):
    if radius == 0:
        return 0

    # 校正参数
    radius = clip(radius, 0, 100)
    amount = clip(amount, 0, 500)
    threshold = clip(threshold, 0, 255)

    # 创建高斯模糊图像
    gauss_data = fast_gauss_filter(src.copy(), radius)

    # 创建掩模图像
    mask_data = np.where(abs(src - gauss_data) < threshold, 0, 128)

    # 再次高斯滤波掩模图像
    mask_data = fast_gauss_filter(mask_data, radius)

    # 计算 USM 锐化后的图像
    diff = src - gauss_data
    adjusted_diff = src + ((diff * amount) >> 7)

    # 根据掩模调整原始和锐化像素值
    result = ((adjusted_diff * mask_data) + (src * (128 - mask_data))) >> 7
    result = np.clip(result, 0, 255)

    return result.astype(np.uint8)

def writeimage_with_bg(arr,bg,alpha,filepath,if_sharp=False):

    height, width, _ = bg.shape
    arr = prepare(arr.transpose((1, 2, 0)))
    if if_sharp:
        arr = usm_sharpen(arr)
    # bg = bg.transpose((1, 2, 0))
    alpha = alpha.transpose((1, 2, 0))
    radiance = arr*255 + (1 - alpha) * bg
    cv2.imwrite(filepath, radiance)

def writeimage(arr,filepath):
    arr = prepare(arr.transpose((1, 2, 0)))
    radiance = (arr) * 255
    cv2.imwrite(filepath, radiance)

