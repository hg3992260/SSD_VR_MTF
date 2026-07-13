import numpy as np
import matplotlib.pyplot as plt
import cv2
import os
import ast
from tools.prepare_data import *
def find_exr_files(directory):
    """获取指定目录下所有后缀为 .exr 的文件名"""
    exr_files = []
    # 遍历目录中的所有文件和目录名
    for filename in os.listdir(directory):
        # 检查文件后缀是否为 .exr
        if filename.endswith(".exr"):
            exr_files.append(filename)
    return exr_files
def exrpath2img(exrpath,outputpath):
    # 将一个路径下所有的exr文件都转成img保存
    exr_files = find_exr_files(exrpath)

    for file in exr_files:
        arr = (prepare(get_volumn_radiance(exrpath+file))*255).astype(np.uint8)
        file = file[:-3]+"png"
        cv2.imwrite(outputpath+file, arr)


def plot_histogram(data):
    """
    绘制给定数据的直方图，数据应为二维浮点数numpy数组。
    直方图将数据分为255个区间，根据数据的实际范围动态设置。

    :param data: 二维浮点数numpy数组
    """
    # 计算数据的最小值和最大值
    data_min = data.min()
    data_max = data.max()

    # 计算直方图
    histogram, bin_edges = np.histogram(data, bins=255, range=(data_min, data_max))

    # 绘制直方图
    plt.figure()
    plt.title("Histogram with 255 bins")
    plt.xlabel("Value")
    plt.ylabel("Frequency")

    plt.bar(bin_edges[:-1], histogram, width=np.diff(bin_edges), align='edge', edgecolor='black')
    plt.xlim(data_min, data_max)
    plt.grid(axis='y', alpha=0.75)
    plt.show()

def get_matrix(exrpath):
    exr_file = OpenEXR.InputFile(exrpath)
    # 读取头部信息
    header = exr_file.header()
    # 关闭文件
    exr_file.close()
    # 打印头部信息

    VolumeToWorld =np.reshape(ast.literal_eval(header['VolumeToWorld'].decode('utf-8')), (4, 4))
    World2Camera = np.reshape(ast.literal_eval(header['World2Camera'].decode('utf-8')), (4, 4))
    Camera2Screen = np.reshape(ast.literal_eval(header['Camera2Screen'].decode('utf-8')), (4, 4))
    Screen2Raster = np.reshape(ast.literal_eval(header['Screen2Raster'].decode('utf-8')), (4, 4))
    return Screen2Raster @ Camera2Screen @ World2Camera @ VolumeToWorld


#outputpath = "D:\\DataSets\\volumndatasets\\0614\\images\\test\\512spp\\"
# exrpath = "D:\\DataSets\\volumndatasets\\0614\\val\\4-artifix\\512spp\\"
# exrpath2img(exrpath,"./Gbuffers.png")

# # 直方图分析
# exrpath = "E://DataSets//GBuffers.exr"
# matrix = get_matrix(exrpath)
# print(matrix)
# exr_file = OpenEXR.InputFile(exrpath)
# print(exr_file.header()['channels'])
# position = get_position(exrpath)
# radiance = get_volumn_radiancedalpha(exrpath)
# print(position.shape)
# for i in range(len(position)):
#     for j in range(len(position[0])):
#         if np.all(np.array(radiance[i][j]) != 0):
#
#             rgb = matrix@(np.append(position[i][j], 1))
#             rgb3 = [rgb[0]/rgb[3],rgb[1]/rgb[3],rgb[2]/rgb[3]]
#             print(rgb3)
#             print(i,end=" ")
#             print(j)
            # print(radiance[i][j])




