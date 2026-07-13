import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F

__all__ = ['Single_Model']
device = torch.device("cuda:0")

import torch
import torch.nn as nn
import torch.nn.functional as F

import torch
from torch import nn

class SEBlock(nn.Module):
    def __init__(self, input_channel, reduction_ratio=16):
        super(SEBlock, self).__init__()
        self.squeeze = nn.AdaptiveAvgPool2d(1)
        self.excitation = nn.Sequential(
            nn.Linear(input_channel, input_channel // reduction_ratio),
            nn.ReLU(inplace=True),
            nn.Linear(input_channel // reduction_ratio, input_channel),
            nn.Sigmoid()
        )

    def forward(self, x):
        batch_size, channel, _, _ = x.size()
        y = self.squeeze(x).view(batch_size, channel)
        y = self.excitation(y).view(batch_size, channel, 1, 1)
        return x * y



class Ea_block(nn.Module):
    def __init__(self, in_channels, out_channels, se_reduction_ratio=16,leaky_relu_slope=0.1):
        # se_reduction_ratio 是SE的参数，se_reduction_ratio越大，越轻量，牺牲表达能力
        super().__init__()

        self.conv1 = nn.Conv2d(in_channels, out_channels, 3, padding=1)
        self.ln1 = nn.InstanceNorm2d(out_channels)
        self.relu = nn.LeakyReLU(negative_slope=leaky_relu_slope)
        self.conv2 = nn.Conv2d(out_channels, out_channels, 3, padding=1)
        self.ln2 = nn.InstanceNorm2d(out_channels)
        # self.relu = nn.Hardswish(inplace=True)
        self.se = SEBlock(out_channels, reduction_ratio=se_reduction_ratio)

    def forward(self, x):
        out = self.conv1(x)
        out = self.ln1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.ln2(out)
        out = self.relu(out)

        out = self.se(out)
        return out

class Eb_block(nn.Module):
    def __init__(self, in_channels, out_channels, se_reduction_ratio=16,leaky_relu_slope=0.1):
        # se_reduction_ratio 是SE的参数，se_reduction_ratio越大，越轻量，牺牲表达能力
        super().__init__()

        self.conv1 = nn.Conv2d(in_channels, out_channels, 3, padding=1)
        self.ln1 = nn.InstanceNorm2d(out_channels)
        self.relu = nn.LeakyReLU(negative_slope=leaky_relu_slope)
        self.conv2 = nn.Conv2d(out_channels, out_channels, 3, padding=1)
        self.ln2 = nn.InstanceNorm2d(out_channels)
        # self.bn2 = nn.InstanceNorm2d(out_channels)
        # self.relu = nn.Hardswish(inplace=True)
        self.se = SEBlock(out_channels, reduction_ratio=se_reduction_ratio)

    def forward(self, x):
        out = self.conv1(x)
        out = self.ln1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.ln2(out)
        out = self.relu(out)

        out = self.se(out)
        return out
class CFM(nn.Module):
    def __init__(self, in_channels1,in_channels2, out_channels1, out_channels2, dilation_rate=1,leaky_relu_slope=0.1):
        super(CFM, self).__init__()

        self.conv1 = nn.Conv2d(in_channels1, out_channels1, kernel_size=3, padding=dilation_rate,
                               dilation=dilation_rate)
        self.conv2 = nn.Conv2d(in_channels2, out_channels2, kernel_size=3, padding=dilation_rate,
                               dilation=dilation_rate)
        self.bn1 = nn.InstanceNorm2d(out_channels1)
        self.bn2 = nn.InstanceNorm2d(out_channels2)
        self.leaky_relu = nn.LeakyReLU(negative_slope=leaky_relu_slope)
    def forward(self, x1, x2):
        out1 = self.conv1(x1)
        out1_1 = self.bn1(out1)
        out2 = self.conv2(x2)
        out2_1 = self.bn2(out2)
        out = torch.cat([out1_1, out2_1], dim=1)
        out = self.leaky_relu(out)

        return out


class Decoder_student(nn.Module):
    def __init__(self, in_channels, out_channels, se_reduction_ratio=16,leaky_relu_slope=0.1):
        # se_reduction_ratio 是SE的参数，se_reduction_ratio越大，越轻量，牺牲表达能力
        super().__init__()

        self.conv1 = nn.Conv2d(in_channels, out_channels, 3, padding=1)
        self.ln1 = nn.InstanceNorm2d(out_channels)
        self.relu = nn.LeakyReLU(negative_slope=leaky_relu_slope)
        self.conv2 = nn.Conv2d(out_channels, out_channels, 3, padding=1)
        self.bn2 = nn.InstanceNorm2d(out_channels)
        # self.relu = nn.Hardswish(inplace=True)
        self.se = SEBlock(out_channels, reduction_ratio=se_reduction_ratio)

    def forward(self, x):
        out = self.conv1(x)
        # out = self.ln1(out)
        out = self.relu(out)

        out = self.conv2(out)
        # out = self.ln1(out)
        out = self.relu(out)
        out = self.se(out)
        return out



class Single_Model(nn.Module):
    def __init__(self, output_channels=3, input_channels=3, **kwargs):
        super().__init__()
        nb_filter = [32, 64, 128, 256, 512]
        self.pool = nn.AvgPool2d(2, 2)
        self.ea1 = Ea_block(input_channels, nb_filter[0])
        self.ea2 = Ea_block(nb_filter[0], nb_filter[1])
        self.ea3 = Ea_block(nb_filter[1], nb_filter[2]) # ea3输出128
        self.eb1 = Eb_block(input_channels, nb_filter[0])
        self.eb2 = Eb_block(nb_filter[0]+nb_filter[0], 2*(nb_filter[0]+nb_filter[0]))
        self.eb3 = Eb_block(2*(nb_filter[0]+nb_filter[0])+nb_filter[1], 8*nb_filter[0]+2*nb_filter[1])

        # fusion输入和输出通道相同
        self.fusion = CFM(128,384,128,384)
        self.de1 = Decoder_student(512,256)
        self.de2 = Decoder_student(384, 192)
        self.de3 = Decoder_student(224, 112)
        self.de4 = Decoder_student(112, 56)
        self.convfinal2 = nn.Conv2d(56, output_channels, 3, padding=1)
        self.up = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)


    def forward(self, x1,x2):
        # 把数据从0-1改成-1到1
        # x1 = x1 * 2 - 1
        # x2 = x2 * 2 - 1
        ea1_out = self.ea1(self.pool(x1))
        ea2_out = self.ea2(self.pool(ea1_out))
        ea3_out = self.ea3(self.pool(ea2_out))

        eb1_out = self.eb1(self.pool(x2))
        eb2_out = self.eb2(self.pool(torch.cat([ea1_out, eb1_out], 1)))
        eb3_out = self.eb3(self.pool(torch.cat([ea2_out, eb2_out], 1)))
        fusion_out = self.fusion(ea3_out,eb3_out)

        de1out = self.de1(self.up(fusion_out))
        de2out = self.de2(self.up(torch.cat([eb2_out, de1out], 1)))
        de3out = self.de3(self.up(torch.cat([eb1_out, de2out], 1)))
        d4out = self.de4(de3out)
        result = self.convfinal2(d4out)

        # result = result * 0.5 +0.5

        return result

class Discriminator(nn.Module):
    def __init__(self):
        super(Discriminator, self).__init__()

        def discriminator_block(f_in, f_out, drop=0.25, bn=True):
            block = [nn.Conv2d(f_in, f_out, kernel_size=3, stride=2, padding=1, bias=False),
                    nn.LeakyReLU(inplace=True, negative_slope=0.2),
                    nn.Dropout2d(drop)]
            if bn: block.append(nn.BatchNorm2d(f_out))
            return block

        self.model = nn.Sequential(
                *discriminator_block(3, 32, bn=False),
                *discriminator_block(32, 64, bn=True),
                *discriminator_block(64, 128, bn=True),
                *discriminator_block(128, 256, bn=True),
                *discriminator_block(256, 512, bn=True))
        self.pool = nn.AvgPool2d(4)

    def forward(self, x):
        x = x * 2 - 1 # zero centered input
        x = self.model(x)
        x = self.pool(x)
        return x # output in [-1, 1]


class MLP(nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim):
        super(MLP, self).__init__()
        self.fc1 = nn.Linear(input_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, output_dim)

    def forward(self, x):
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return x



class Teacher_Model(nn.Module):
    def __init__(self, output_channels=3, input_channels=3,**kwargs):
        super().__init__()
        nb_filter = [32, 64, 128, 256, 512]
        self.pool = nn.MaxPool2d(2, 2)
        self.ea1 = Ea_block(input_channels, nb_filter[0])
        self.ea2 = Ea_block(nb_filter[0], nb_filter[1])
        self.ea3 = Ea_block(nb_filter[1], nb_filter[2]) # ea3输出128
        self.ea4 = Ea_block(nb_filter[2], nb_filter[3])  # ea3输出128
        self.eb1 = Eb_block(input_channels, nb_filter[0])
        self.eb2 = Eb_block(nb_filter[0]+nb_filter[0], 2*(nb_filter[0]+nb_filter[0]))
        self.eb3 = Eb_block(2*(nb_filter[0]+nb_filter[0])+nb_filter[1], 8*nb_filter[0]+2*nb_filter[1])
        self.eb4 = Eb_block(8*nb_filter[0]+2*nb_filter[1]+nb_filter[2],16*nb_filter[0]+4*nb_filter[1]+2*nb_filter[2])
        # fusion输入和输出通道相同
        self.fusion = CFM(256,1024,256,1024)
        self.de1 = Decoder_student(1280,640)
        self.de2 = Decoder_student(1024, 512)
        self.de3 = Decoder_student(640, 320)
        self.de4 = Decoder_student(352, 176)
        self.de5 = Decoder_student(176, 88)
        self.convfinal2 = nn.Conv2d(88, output_channels, 3, padding=1)
        # self.up = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)


        # 添加 MLP 模块，假设隐藏层和输出层的维度与输入维度相同
        self.mlp = MLP(input_dim=88, hidden_dim=88, output_dim=88)


    def forward(self, x1,x2):
        # print(2)

        ea1_out = self.ea1(self.pool(x1))
        ea2_out = self.ea2(self.pool(ea1_out))
        ea3_out = self.ea3(self.pool(ea2_out))
        ea4_out = self.ea4(self.pool(ea3_out))
        eb1_out = self.eb1(self.pool(x2))
        eb2_out = self.eb2(self.pool(torch.cat([ea1_out, eb1_out], 1)))
        eb3_out = self.eb3(self.pool(torch.cat([ea2_out, eb2_out], 1)))
        eb4_out = self.eb4(self.pool(torch.cat([ea3_out, eb3_out], 1)))
        fusion_out = self.fusion(ea4_out,eb4_out)

        # print(3)
        de1out = self.de1(F.interpolate(fusion_out,scale_factor=2))
        # print(torch.cat([eb3_out, de1out], 1).shape)
        de2out = self.de2(F.interpolate(torch.cat([eb3_out, de1out], 1),scale_factor=2))

        de3out = self.de3(F.interpolate(torch.cat([eb2_out, de2out], 1),scale_factor=2))
        # print(torch.cat([eb1_out, de3out], 1).shape)
        de4out = self.de4(F.interpolate(torch.cat([eb1_out, de3out], 1),scale_factor=2))
        de5out = self.de5(de4out)
        # print(de5out.shape)
        # 将 de4out 重新形状为 (batch_size * width * height, channels) 以便应用 MLP
        # batch_size, channels, height, width = de5out.size()
        # de5out_flat = de5out.permute(0, 2, 3, 1).contiguous().view(-1, channels)

        # 对每个像素点应用 MLP
        # mlp_out_flat = self.mlp(de5out_flat)
        # mlp_out = mlp_out_flat.view(batch_size, height, width, channels).permute(0, 3, 1, 2).contiguous()
        result = self.convfinal2(de5out)

        return result




