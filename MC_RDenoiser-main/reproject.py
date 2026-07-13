from tools.prepare_data import *
import ast

# 根据exr头文件得到转换矩阵。一个场景中的转换矩阵是一样的，只需要算一次
def get_matrix(exrpath):
    exr_file = OpenEXR.InputFile(exrpath)
    # 读取头部信息
    header = exr_file.header()
    # 打印头部信息
    VolumeToWorld =np.reshape(ast.literal_eval(header['VolumeToWorld'].decode('utf-8')), (4, 4))
    World2Camera = np.reshape(ast.literal_eval(header['World2Camera'].decode('utf-8')), (4, 4))
    Camera2Screen = np.reshape(ast.literal_eval(header['Camera2Screen'].decode('utf-8')), (4, 4))
    Screen2Raster = np.reshape(ast.literal_eval(header['Screen2Raster'].decode('utf-8')), (4, 4))
    convertMatrix = Screen2Raster @ Camera2Screen @ World2Camera @ VolumeToWorld

    channel_names = ["SingleRadi_B", "SingleRadi_G", "SingleRadi_R","Alpha","Pos_X","Pos_Y","Pos_Z"]
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
    Position = np.stack((channel_datas[4], channel_datas[5], channel_datas[6]), axis=2)
    # Rad_noalpha = divide(Radiance, Alpha)
    # 关闭文件
    exr_file.close()
    return convertMatrix, Radiance, Position
from tools.visulization import exrpath2img

def preproject_exr(t):
    cur_exr_file = exrpath + "img-{}.exr".format(t)
    pre_exr_file = exrpath + "img-{}.exr".format(t-1)
    cur_matrix, cur_radi,cur_position = get_matrix(cur_exr_file)
    pre_matrix, pre_radi,pre_position = get_matrix(pre_exr_file)
    results = np.zeros_like(pre_radi)
    for i in range(cur_radi.shape[0]):
        for j in range(cur_radi.shape[1]):
            if np.all(np.array(cur_radi[i][j]) != 0):
                out = pre_matrix @ (np.append(cur_position[i][j], 1))
                pre_screenpos = [out[0] / out[3], out[1] / out[3], out[2] / out[3]]
                prei,prej = int(pre_screenpos[0]/ pre_screenpos[2]), int(pre_screenpos[1]/ pre_screenpos[2])
                if prei in range(0,cur_radi.shape[1]) and prej in range(0,cur_radi.shape[0]):
                    results[i][j] = pre_radi[prej][prei]
                else:
                    results[i][j] = cur_radi[i][j]

    print(results.shape)
    print(pre_radi.shape)
    cv2.imwrite("out.png", (prepare(results)*255).astype(np.uint8))

# 先读取模型去噪后的png图像，再读取exr中的position。利用历史帧的position和radiance投影到当前帧。
def preproject_png(t):
    cur_file = exrpath + "img-{}.png".format(t)
    pre_file = exrpath + "img-{}.png".format(t-1)

    cur_matrix, cur_radi,cur_position = get_matrix(cur_file)
    pre_matrix, pre_radi,pre_position = get_matrix(pre_file)
    pre_radi = cv2.imread("E:\\DataSets\\results\\4-artifix-8sppdenoised0.png")
    results = np.zeros_like(pre_radi)
    for i in range(cur_radi.shape[0]):
        for j in range(cur_radi.shape[1]):
            if np.all(np.array(cur_radi[i][j]) != 0):
                out = pre_matrix @ (np.append(cur_position[i][j], 1))
                pre_screenpos = [out[0] / out[3], out[1] / out[3], out[2] / out[3]]
                prei,prej = int(pre_screenpos[0]/ pre_screenpos[2]), int(pre_screenpos[1]/ pre_screenpos[2])
                if prei in range(0,cur_radi.shape[1]) and prej in range(0,cur_radi.shape[0]):
                    results[i][j] = pre_radi[prej][prei]
                else:
                    results[i][j] = cur_radi[i][j]
    cv2.imwrite("out.png", (prepare(results)*255).astype(np.uint8))


exrpath = "D:\\DataSets\\volumndatasets\\reproject\\train\\4-artifix\\8spp\\"
pngpath = "D:\\DataSets\\volumndatasets\\reproject\\train\\4-artifix\\8spp\\"
exrpath2img(exrpath,exrpath)
preproject_exr(1)