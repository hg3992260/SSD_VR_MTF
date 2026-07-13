import OpenEXR
import Imath
import os

if __name__ == "__main__":

    input_exr_path = 'D:\\DataSets\\volumndatasets\\0614\\train\\3-dog\\2spp\\img-0.exr'
    outputpath = 'D:\\DataSets\\volumndatasets\\0614\\seperatebuffer\\'
    exr_file = OpenEXR.InputFile(input_exr_path)
    # 获取 EXR 文件的头部信息
    header = exr_file.header()
    width = header['dataWindow'].max.x - header['dataWindow'].min.x + 1
    height = header['dataWindow'].max.y - header['dataWindow'].min.y + 1

    # 获取通道名列表
    channel_names = list(header["channels"].keys())

    # 遍历每个通道,并将其保存为独立的 EXR 文件
    for channel_name in channel_names:
        # 读取通道数据
        channel_data = exr_file.channel(channel_name, Imath.PixelType(Imath.PixelType.FLOAT))

        # 创建输出 EXR 文件的头部信息
        output_header = OpenEXR.Header(width, height)
        output_header['channels'] ={
            channel_name: Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT))
        }
        # 创建输出 EXR 文件

        output_path = os.path.join(outputpath,
                                   f"{os.path.splitext(os.path.basename(input_exr_path))[0]}_{channel_name}.exr")
        output_file = OpenEXR.OutputFile(output_path, output_header)

        # 写入输出 EXR 文件
        output_file.writePixels({channel_name: channel_data})
        output_file.close()
