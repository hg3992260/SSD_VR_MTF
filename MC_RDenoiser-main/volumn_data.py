from tools.prepare_data import *
import cv2
from matplotlib import cm
from matplotlib.colors import ListedColormap, LinearSegmentedColormap
import matplotlib.pyplot as plt


def new_data():
    filename = 'D://DataSets//volumndatasets//fusiondataset//256spp//img-0 (4).exr'
    # filename = "D://DataSets//volumndatasets//manix-1//15spp//img-30.exr"
    # illu = get_illu_noise(filename)
    exr_file = OpenEXR.InputFile(filename)
    header = exr_file.header()
    print(header)
    channel_names = ["Illumin_B", "Illumin_G", "Illumin_R", "SingleRadiDividedBySdf_B", "SingleRadiDividedBySdf_G",
                     "SingleRadiDividedBySdf_R", "SingleRadi_B", "SingleRadi_G", "SingleRadi_R",
                     "Sdf_B", "Sdf_G", "Sdf_R"]
    # channel_names = ["Alpha", "Depth", "Illumin_B","Illumin_G","Illumin_R","Sdf_B","Sdf_G","Sdf_R","Radi_B","Radi_G","Radi_R"]
    channel_datas = []
    for channelname in channel_names:
        half_channel = exr_file.channel(channelname, Imath.PixelType(Imath.PixelType.HALF))
        width = header['dataWindow'].max.x - header['dataWindow'].min.x + 1
        height = header['dataWindow'].max.y - header['dataWindow'].min.y + 1
        half_array = np.frombuffer(half_channel, dtype=np.float16)
        half_array = np.reshape(half_array, (height, width))

        channel_datas.append(half_array)
    channel_datas = np.array(channel_datas)

    Illumin = np.stack((channel_datas[0], channel_datas[1], channel_datas[2]), axis=2)
    Sdf = np.stack((channel_datas[5], channel_datas[6], channel_datas[7]), axis=2)
    Alpha = np.stack((channel_datas[0], channel_datas[0], channel_datas[0]), axis=2)
    rad = np.stack((channel_datas[6], channel_datas[7], channel_datas[8]), axis=2)
    # Illumin_noalpha = divide(Illumin, Alpha)
    print(rad.max())
    print(rad.min())
    #
    # print(Illumin.min())
    # print(Illumin.max())

    Sdf_noalpha = divide(Sdf, Alpha)
    Illumin_noalpha = divide(Illumin, Alpha)

    # Ilumin = prepare(Illumin)
    # Radiance = np.stack((channel_datas[8], channel_datas[9], channel_datas[10]), axis=2)
    # Radiance = Sdf_noalpha * Illumin_noalpha
    Radiance = prepare(rad)
    Sdf_noalpha = prepare(Sdf_noalpha)

    # Radiance = (Radiance - 0) / (Radiance.max() - 0)
    scaled_array = (Radiance * 255).astype(np.uint8)

    # print(Radiance.max())
    # print(Radiance.min())

    cv2.imwrite("./volumn_data/{}.png".format("Radiance"), scaled_array)
from train import *
def draw_errormap(img1,img2):

    return pow(img1 - img2,2)*100
def plot_examples(data,colormaps):
    np.random.seed(19680801)
    data = data[500:1000,500:1000,0]
    print(data.shape)
    n = len(colormaps)
    fig, axs = plt.subplots(1, n, figsize=(n * 2 + 2, 3),
                            constrained_layout=True, squeeze=False)
    for [ax, cmap] in zip(axs.flat, colormaps):
        psm = ax.pcolormesh(data, cmap=cmap, rasterized=True, vmin=-0.01, vmax=0.01)
        fig.colorbar(psm, ax=ax)
    plt.show()



if __name__=="__main__":
    # new_data()
    filename1 = "D://DataSets//volumndatasets//0614//train//1-manix//8spp//img-0.exr"
    filename2 = "D://DataSets//volumndatasets//0614//train//1-manix//512spp//img-0.exr"
    illu1 = get_sdf(filename1)
    illu2 = get_sdf(filename2)
    result = draw_errormap(illu1, illu2)
    print(result.max())
    print(result.min())

    viridis = cm.get_cmap('viridis', 256)
    newcolors = viridis(np.linspace(0, 1, 256))
    pink = np.array([248 / 256, 24 / 256, 148 / 256, 1])

    newcmp = ListedColormap(newcolors)

    plot_examples(result, [viridis, newcmp])

    print(result.max())
    print(result.min())
    scaled_array = (result * 255).astype(np.uint8)
    cv2.imwrite("./volumn_data/{}.png".format("error"), scaled_array)

    # filename = 'D://DataSets//GBuffers.exr'
    # # filename = "D://DataSets//volumndatasets//manix-1//15spp//img-30.exr"
    # # illu = get_illu_noise(filename)
    # exr_file = OpenEXR.InputFile(filename)
    # header = exr_file.header()
    # print(header)
    # channel_names = ["Illumin_B", "Illumin_G", "Illumin_R", "SingleRadiDividedBySdf_B", "SingleRadiDividedBySdf_G", "SingleRadiDividedBySdf_R", "SingleRadi_B", "SingleRadi_G", "SingleRadi_R",
    #                  "Sdf_B", "Sdf_G","Sdf_R"]
    # # channel_names = ["Alpha", "Depth", "Illumin_B","Illumin_G","Illumin_R","Sdf_B","Sdf_G","Sdf_R","Radi_B","Radi_G","Radi_R"]
    # channel_datas = []
    # for channelname in channel_names:
    #     half_channel = exr_file.channel(channelname, Imath.PixelType(Imath.PixelType.HALF))
    #     width = header['dataWindow'].max.x - header['dataWindow'].min.x + 1
    #     height = header['dataWindow'].max.y - header['dataWindow'].min.y + 1
    #     half_array = np.frombuffer(half_channel, dtype=np.float16)
    #     half_array = np.reshape(half_array, (height, width))
    #
    #     channel_datas.append(half_array)
    # channel_datas = np.array(channel_datas)
    #
    # Illumin = np.stack((channel_datas[2], channel_datas[3], channel_datas[4]), axis=2)
    # Sdf = np.stack((channel_datas[5], channel_datas[6], channel_datas[7]), axis=2)
    # Alpha = np.stack((channel_datas[0], channel_datas[0], channel_datas[0]), axis=2)
    # # Illumin_noalpha = divide(Illumin, Alpha)
    #
    # #
    # # print(Illumin.min())
    # # print(Illumin.max())
    #
    #
    # Sdf_noalpha = divide(Sdf, Alpha)
    # Illumin_noalpha = divide(Illumin, Alpha)
    #
    # # Ilumin = prepare(Illumin)
    # Radiance = np.stack((channel_datas[8], channel_datas[9], channel_datas[10]), axis=2)
    # # Radiance = Sdf_noalpha * Illumin_noalpha
    # Radiance = prepare(Radiance)
    # Sdf_noalpha = prepare(Sdf_noalpha)
    #
    # # Radiance = (Radiance - 0) / (Radiance.max() - 0)
    # scaled_array = (Sdf_noalpha * 255).astype(np.uint8)
    #
    # # print(Radiance.max())
    # # print(Radiance.min())
    #
    #
    # cv2.imwrite("./volumn_data/{}.png".format("Radiance"), scaled_array)
    # # for i in range(8):
    # #
    # #     image = channel_datas[i]
    # #     scaled_array = (image * 255).astype(np.uint8)
    # #     cv2.imwrite("./volumn_data/{}.png".format(channel_names[i]), scaled_array)

