import torch
import torch.nn as nn
from torch.nn import functional as func
import numpy as np
import torch.nn.functional as F
from torch.autograd import Variable
from math import exp
__all__ = ['SMAPELoss','l1loss','SMAPELosstemp']

def LoG(img):
    weight = [
        [0, 0, 1, 0, 0],
        [0, 1, 2, 1, 0],
        [1, 2, -16, 2, 1],
        [0, 1, 2, 1, 0],
        [0, 0, 1, 0, 0]
    ]
    weight = np.array(weight)

    weight_np = np.zeros((1, 1, 5, 5))
    weight_np[0, 0, :, :] = weight
    weight_np = np.repeat(weight_np, img.shape[1], axis=1)
    weight_np = np.repeat(weight_np, img.shape[0], axis=0)

    weight = torch.from_numpy(weight_np).type(torch.FloatTensor).to('cuda:0')

    return func.conv2d(img, weight, padding=1)

class SMAPELoss_kd(nn.Module):
    def __init__(self, eps=0.01):
        super().__init__()
        self.eps = eps

    def forward(self,student_outputs, teacher_outputs, targets):

        loss1 = torch.mean(torch.abs(student_outputs - targets) / (student_outputs.abs() + targets.abs() + self.eps))
        loss2 = torch.mean(torch.abs(student_outputs - teacher_outputs) / (student_outputs.abs() + teacher_outputs.abs() + self.eps))
        return loss1+loss2
class SMAPELoss(nn.Module):
    def __init__(self, eps=0.01):
        super().__init__()
        self.eps = eps

    def forward(self,outputs, targets):

        loss = torch.mean(torch.abs(outputs - targets) / (outputs.abs() + targets.abs() + self.eps))

        return loss
class SMAPELosstemp(nn.Module):
    def __init__(self, eps=0.01):
        super().__init__()
        self.eps = eps

    def forward(self,student_outputs, teacher_outputs, targets):
        meanloss = 0

        for i in range(len(targets)):

            so = student_outputs[:,i*3:(i+1)*3,:,:]
            to = teacher_outputs[:,i*3:(i+1)*3,:,:]
            tg = targets[i]

            tg = tg.to('cuda')
            # print(so.shape)
            # print(tg.shape)
            # print(to.shape)
            loss_1 = torch.mean(torch.abs(so - tg) / (so.abs() + tg.abs() + self.eps))
            loss_2 = torch.mean(torch.abs(so - to) / (so.abs() + to.abs() + self.eps))
            meanloss += (loss_1 + loss_2)
        meanloss = meanloss/len(targets)

        return meanloss

def HFEN(output, target):
    return torch.sum(torch.pow(LoG(output) - LoG(target), 2)) / torch.sum(torch.pow(LoG(target), 2))

class l1loss(nn.Module):
    def __init__(self):
        super().__init__()


    def forward(self, outputs, targets):
        l1loss = torch.sum(torch.abs(outputs - targets)) / torch.numel(outputs)
        HFENloss = HFEN(outputs, targets)
        return 0.8* l1loss + 0.2 * HFENloss

class Reeloss_kd(nn.Module):
    def __init__(self):
        super().__init__()

    # 知识蒸馏
    def forward(self, student_outputs, teacher_outputs, targets):
        l1loss = torch.sum(torch.abs(student_outputs - targets)) / torch.numel(student_outputs)
        HFENloss = HFEN(student_outputs, targets)
        loss1 = 0.8* l1loss + 0.2 * HFENloss
        l1loss = torch.sum(torch.abs(student_outputs - teacher_outputs)) / torch.numel(student_outputs)
        HFENloss = HFEN(student_outputs, teacher_outputs)
        loss2 = 0.8* l1loss + 0.2 * HFENloss
        return loss2 + loss1


def calculate_rae(image1, image2):
    # 将图像转换为numpy数组
    # image1 = np.array(image1)
    # image2 = np.array(image2)
    #
    # # 确保图像尺寸相同
    # assert image1.shape == image2.shape, "图像尺寸不匹配"

    # 计算RAE
    diff = np.abs(image1 - image2)
    rae = np.sum(diff) / np.sum(image1)

    return rae


class RAEloss_kd(nn.Module):
    def __init__(self):
        super(RAEloss_kd, self).__init__()

    def forward(self, student_outputs, teacher_outputs, targets):


        diff = torch.abs(student_outputs - targets)
        rae1 = torch.sum(diff) / torch.sum(targets)

        diff = torch.abs(teacher_outputs - targets)
        rae2 = torch.sum(diff) / torch.sum(targets)

        return rae1+rae2

class RAEloss(nn.Module):
    def __init__(self):
        super(RAEloss, self).__init__()

    def forward(self, outputs, targets):
        diff = torch.abs(outputs - targets)
        rae1 = torch.sum(diff) / torch.sum(targets)


        return rae1

class RAEloss_temp(nn.Module):
    def __init__(self):
        super(RAEloss_temp, self).__init__()

    def forward(self, outputs, targets):
        targets = targets.cuda()
        targets = targets[:,-1,:,:,:]
        diff = torch.abs(outputs - targets)
        rae1 = torch.sum(diff) / torch.sum(targets)


        return rae1

class L1SpecLoss(torch.nn.Module):
    def __init__(self):
        super(L1SpecLoss, self).__init__()
        self.kernel_mean = torch.ones((3, 1, 11, 11)) / (11**2)

    def forward(self, img1, img2):
        # L1 loss
        L1 = F.l1_loss(img1, img2)
        # spec loss
        if img1.is_cuda: self.kernel_mean = self.kernel_mean.cuda()
        lm1 = F.conv2d(img1, self.kernel_mean, padding=11//2, groups=3)
        lm2 = F.conv2d(img2, self.kernel_mean, padding=11//2, groups=3)
        Ls = F.l1_loss(torch.clamp(img1 - lm1, 0, 1), torch.clamp(img2 - lm2, 0, 1))
        return 0.8 * L1 + 0.2 * Ls
class MS_SSIM_L1_LOSS(nn.Module):
    # Have to use cuda, otherwise the speed is too slow.
    def __init__(self, gaussian_sigmas=[0.5, 1.0, 2.0, 4.0, 8.0],
                 data_range = 1.0,
                 K=(0.01, 0.03),
                 alpha=0.025,
                 compensation=200.0,
                 cuda_dev=0,):
        super(MS_SSIM_L1_LOSS, self).__init__()
        self.DR = data_range
        self.C1 = (K[0] * data_range) ** 2
        self.C2 = (K[1] * data_range) ** 2
        self.pad = int(2 * gaussian_sigmas[-1])
        self.alpha = alpha
        self.compensation=compensation
        filter_size = int(4 * gaussian_sigmas[-1] + 1)
        g_masks = torch.zeros((3*len(gaussian_sigmas), 1, filter_size, filter_size))
        for idx, sigma in enumerate(gaussian_sigmas):
            # r0,g0,b0,r1,g1,b1,...,rM,gM,bM
            g_masks[3*idx+0, 0, :, :] = self._fspecial_gauss_2d(filter_size, sigma)
            g_masks[3*idx+1, 0, :, :] = self._fspecial_gauss_2d(filter_size, sigma)
            g_masks[3*idx+2, 0, :, :] = self._fspecial_gauss_2d(filter_size, sigma)
        self.g_masks = g_masks.cuda(cuda_dev)

    def _fspecial_gauss_1d(self, size, sigma):
        """Create 1-D gauss kernel
        Args:
            size (int): the size of gauss kernel
            sigma (float): sigma of normal distribution

        Returns:
            torch.Tensor: 1D kernel (size)
        """
        coords = torch.arange(size).to(dtype=torch.float)
        coords -= size // 2
        g = torch.exp(-(coords ** 2) / (2 * sigma ** 2))
        g /= g.sum()
        return g.reshape(-1)

    def _fspecial_gauss_2d(self, size, sigma):
        """Create 2-D gauss kernel
        Args:
            size (int): the size of gauss kernel
            sigma (float): sigma of normal distribution

        Returns:
            torch.Tensor: 2D kernel (size x size)
        """
        gaussian_vec = self._fspecial_gauss_1d(size, sigma)
        return torch.outer(gaussian_vec, gaussian_vec)

    def forward(self, x, y):
        # print(y.shape)
        # print(x.shape)
        b, c, h, w = x.shape
        mux = F.conv2d(x, self.g_masks, groups=3, padding=self.pad)
        muy = F.conv2d(y, self.g_masks, groups=3, padding=self.pad)

        mux2 = mux * mux
        muy2 = muy * muy
        muxy = mux * muy

        sigmax2 = F.conv2d(x * x, self.g_masks, groups=3, padding=self.pad) - mux2
        sigmay2 = F.conv2d(y * y, self.g_masks, groups=3, padding=self.pad) - muy2
        sigmaxy = F.conv2d(x * y, self.g_masks, groups=3, padding=self.pad) - muxy

        # l(j), cs(j) in MS-SSIM
        l  = (2 * muxy    + self.C1) / (mux2    + muy2    + self.C1)  # [B, 15, H, W]
        cs = (2 * sigmaxy + self.C2) / (sigmax2 + sigmay2 + self.C2)

        lM = l[:, -1, :, :] * l[:, -2, :, :] * l[:, -3, :, :]
        PIcs = cs.prod(dim=1)

        loss_ms_ssim = 1 - lM*PIcs  # [B, H, W]

        loss_l1 = F.l1_loss(x, y, reduction='none')  # [B, 3, H, W]
        # average l1 loss in 3 channels
        gaussian_l1 = F.conv2d(loss_l1, self.g_masks.narrow(dim=0, start=-3, length=3),
                               groups=3, padding=self.pad).mean(1)  # [B, H, W]

        loss_mix = self.alpha * loss_ms_ssim + (1 - self.alpha) * gaussian_l1 / self.DR
        loss_mix = self.compensation*loss_mix

        return loss_mix.mean()



# class MS_SSIM_L1_LOSS_temp(nn.Module):
#     # Have to use cuda, otherwise the speed is too slow.
#     def __init__(self, gaussian_sigmas=[0.5, 1.0, 2.0, 4.0, 8.0],
#                  data_range = 1.0,
#                  K=(0.01, 0.03),
#                  alpha=0.025,
#                  compensation=200.0,
#                  cuda_dev=0,):
#         super(MS_SSIM_L1_LOSS_temp, self).__init__()
#         self.DR = data_range
#         self.C1 = (K[0] * data_range) ** 2
#         self.C2 = (K[1] * data_range) ** 2
#         self.pad = int(2 * gaussian_sigmas[-1])
#         self.alpha = alpha
#         self.compensation=compensation
#         filter_size = int(4 * gaussian_sigmas[-1] + 1)
#         g_masks = torch.zeros((3*len(gaussian_sigmas), 1, filter_size, filter_size))
#         for idx, sigma in enumerate(gaussian_sigmas):
#             # r0,g0,b0,r1,g1,b1,...,rM,gM,bM
#             g_masks[3*idx+0, 0, :, :] = self._fspecial_gauss_2d(filter_size, sigma)
#             g_masks[3*idx+1, 0, :, :] = self._fspecial_gauss_2d(filter_size, sigma)
#             g_masks[3*idx+2, 0, :, :] = self._fspecial_gauss_2d(filter_size, sigma)
#         self.g_masks = g_masks.cuda(cuda_dev)
#
#     def _fspecial_gauss_1d(self, size, sigma):
#         """Create 1-D gauss kernel
#         Args:
#             size (int): the size of gauss kernel
#             sigma (float): sigma of normal distribution
#
#         Returns:
#             torch.Tensor: 1D kernel (size)
#         """
#         coords = torch.arange(size).to(dtype=torch.float)
#         coords -= size // 2
#         g = torch.exp(-(coords ** 2) / (2 * sigma ** 2))
#         g /= g.sum()
#         return g.reshape(-1)
#
#     def _fspecial_gauss_2d(self, size, sigma):
#         """Create 2-D gauss kernel
#         Args:
#             size (int): the size of gauss kernel
#             sigma (float): sigma of normal distribution
#
#         Returns:
#             torch.Tensor: 2D kernel (size x size)
#         """
#         gaussian_vec = self._fspecial_gauss_1d(size, sigma)
#         return torch.outer(gaussian_vec, gaussian_vec)
#
#     def forward(self, x, y):
#         # x:output, y:target
#         y = y[:,-1,:,:,:]
#         print(y.shape)
#         print(x.shape)
#         b, c, h, w = x.shape
#         mux = F.conv2d(x, self.g_masks, groups=3, padding=self.pad)
#         muy = F.conv2d(y, self.g_masks, groups=3, padding=self.pad)
#
#         mux2 = mux * mux
#         muy2 = muy * muy
#         muxy = mux * muy
#
#         sigmax2 = F.conv2d(x * x, self.g_masks, groups=3, padding=self.pad) - mux2
#         sigmay2 = F.conv2d(y * y, self.g_masks, groups=3, padding=self.pad) - muy2
#         sigmaxy = F.conv2d(x * y, self.g_masks, groups=3, padding=self.pad) - muxy
#
#         # l(j), cs(j) in MS-SSIM
#         l  = (2 * muxy    + self.C1) / (mux2    + muy2    + self.C1)  # [B, 15, H, W]
#         cs = (2 * sigmaxy + self.C2) / (sigmax2 + sigmay2 + self.C2)
#
#         lM = l[:, -1, :, :] * l[:, -2, :, :] * l[:, -3, :, :]
#         PIcs = cs.prod(dim=1)
#
#         loss_ms_ssim = 1 - lM*PIcs  # [B, H, W]
#
#         loss_l1 = F.l1_loss(x, y, reduction='none')  # [B, 3, H, W]
#         # average l1 loss in 3 channels
#         gaussian_l1 = F.conv2d(loss_l1, self.g_masks.narrow(dim=0, start=-3, length=3),
#                                groups=3, padding=self.pad).mean(1)  # [B, H, W]
#
#         loss_mix = self.alpha * loss_ms_ssim + (1 - self.alpha) * gaussian_l1 / self.DR
#         loss_mix = self.compensation*loss_mix
#
#         return loss_mix.mean()

class L1HFENLoss(torch.nn.Module):
    def __init__(self):
        super(L1HFENLoss, self).__init__()
        self.kernel = torch.Tensor([[0, 0, 1, 0, 0], [0, 1, 2, 1, 0], [1, 2, -16, 2, 1], [0, 1, 2, 1, 0], [0, 0, 1, 0, 0]]).repeat((3, 1, 1, 1))

    def forward(self, img1, img2):
        # L1 loss
        L1 = F.l1_loss(img1, img2)
        # HFEN loss
        if img1.is_cuda: self.kernel = self.kernel.cuda()
        log1 = F.conv2d(img1, self.kernel, padding=2, groups=3)
        log2 = F.conv2d(img2, self.kernel, padding=2, groups=3)
        Lhf = F.l1_loss(log1, log2)
        return 0.8 * L1 + 0.2 * Lhf


class L1HFENSpecLoss(L1HFENLoss):
    def __init__(self):
        super(L1HFENSpecLoss, self).__init__()
        self.kernel_mean = torch.ones((3, 1, 11, 11)) / (11**2)

    def forward(self, img1, img2):
        # L1 loss
        L1 = F.l1_loss(img1, img2)
        # HFEN loss
        if img1.is_cuda: self.kernel = self.kernel.cuda()
        log1 = F.conv2d(img1, self.kernel, padding=2, groups=3)
        log2 = F.conv2d(img2, self.kernel, padding=2, groups=3)
        Lhf = F.l1_loss(log1, log2)
        # spec loss
        if img1.is_cuda: self.kernel_mean = self.kernel_mean.cuda()
        lm1 = F.conv2d(img1, self.kernel_mean, padding=11//2, groups=3)
        lm2 = F.conv2d(img2, self.kernel_mean, padding=11//2, groups=3)
        Ls = F.l1_loss(torch.clamp(img1 - lm1, 0, 1), torch.clamp(img2 - lm2, 0, 1))
        return 0.8 * L1 + 0.1 * Lhf + 0.1 * Ls


import torch
import torch.nn as nn
import torch.nn.functional as F

class CombinedLoss(nn.Module):
    def __init__(self, grad_weight=0.5, mse_weight=0.5, loss_type='L1'):
        super(CombinedLoss, self).__init__()
        # 定义Sobel算子核，用于计算x和y方向的梯度，每个核复制对应输入通道数
        self.kernel_x = torch.tensor([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=torch.float32).view(1, 1, 3, 3).repeat(3, 1, 1, 1)
        self.kernel_y = torch.tensor([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=torch.float32).view(1, 1, 3, 3).repeat(3, 1, 1, 1)
        self.grad_weight = grad_weight
        self.mse_weight = mse_weight
        self.loss_type = loss_type

    def forward(self, image, ref):
        # 确保输入是浮点类型，并在GPU上（如果可用）
        device = image.device  # 获取输入图像所在的设备
        self.kernel_x = self.kernel_x.to(device)
        self.kernel_y = self.kernel_y.to(device)

        # 计算图像的梯度
        grad_x_image = F.conv2d(image, self.kernel_x, padding=1, groups=3)
        grad_y_image = F.conv2d(image, self.kernel_y, padding=1, groups=3)

        grad_x_ref = F.conv2d(ref, self.kernel_x, padding=1, groups=3)
        grad_y_ref = F.conv2d(ref, self.kernel_y, padding=1, groups=3)

        # 计算梯度损失
        if self.loss_type == 'L1':
            grad_loss = F.l1_loss(grad_x_image, grad_x_ref) + F.l1_loss(grad_y_image, grad_y_ref)
        elif self.loss_type == 'L2':
            grad_loss = F.mse_loss(grad_x_image, grad_x_ref) + F.mse_loss(grad_y_image, grad_y_ref)
        else:
            raise ValueError("Unsupported loss type. Choose 'L1' or 'L2'.")

        # 计算MSE损失
        mse_loss = F.mse_loss(image, ref)

        # 计算总损失
        total_loss = self.grad_weight * grad_loss + self.mse_weight * mse_loss

        return total_loss