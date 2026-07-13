from argprase import *
import torch
import torch.backends.cudnn as cudnn
import cv2
import time
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt
from datasets import *
from tools.utils import AverageMeter
from volumn_data import prepare
from skimage.metrics import peak_signal_noise_ratio as psnr
from skimage.metrics import structural_similarity as ssim

def calculate_metrics(image1, image2):
    # 确保图像是浮点数类型，这对于PSNR和SSIM计算是必须的


    # 计算PSNR，这可以直接在多通道图像上操作
    psnr_value = psnr(image1, image2, data_range=1.0)

    # 计算SSIM，需要对每个通道分别处理
    ssim_values = [ssim(image1[i, :, :], image2[i, :, :], data_range=image1.max() - image1.min()) for i in range(image1.shape[0])]
    ssim_value = np.mean(ssim_values)  # 取均值得到一个综合的SSIM值
    # print(psnr_value)
    # print(ssim_value)
    return psnr_value, ssim_value


# Define a hook function 获取网络中间层的输出
def get_activation(name):
    def hook(model, input, output):
        feature_maps = output[0].cpu().numpy()
        num_features = 128
        n_components = 2
        perplexity = 30
        learning_rate = 200
        num_samples, height, width = feature_maps.shape
        flattened_features = feature_maps.reshape(num_samples, -1)

        # Select a subset of feature maps to speed up the process
        indices = np.random.choice(flattened_features.shape[0], num_features, replace=False)
        selected_features = flattened_features[indices]

        # Apply t-SNE
        tsne = TSNE(n_components=n_components, perplexity=perplexity, learning_rate=learning_rate)
        tsne_results = tsne.fit_transform(selected_features)

        # Visualize
        plt.figure(figsize=(10, 6))
        plt.scatter(tsne_results[:, 0], tsne_results[:, 1], marker='o', s=30, edgecolor='k')
        plt.title('t-SNE visualization of Feature Maps')
        plt.xlabel('Component 1')
        plt.ylabel('Component 2')
        plt.show()
        print(f"{name} activation shape: {output.shape}")
    return hook

def resize_image(image, target_shape):
    resized_image = cv2.resize(image, (target_shape[1], target_shape[0]), interpolation=cv2.INTER_CUBIC)
    return resized_image

save_path = 'D:\\DataSets\\models\\RDnet\\'
config = vars(parse_args())
results_save_path = 'E:\\DataSets\\results\\' + config['testname']
if not os.path.exists(results_save_path):
    os.makedirs(results_save_path)



def denoise(add_bg = True,save_exr = True):



    cudnn.benchmark = True


    device = torch.device("cuda")
    print('{}{}//model.pt'.format(save_path, config['testname']))
    model = torch.load( '{}{}//model.pt'.format(save_path, config['testname']), map_location=device)
    # 定义什么地方激活钩子函数
    # hook_handle1 = model.ea3.register_forward_hook(get_activation('ea3'))
    # hook_handle2 = model.eb3.register_forward_hook(get_activation('eb3'))

    # 读数据
    test_dataset = DataSetPredict(
        img_dir=os.path.join(config['testpath'], config['testdataset'], config['noisetype']),
        ref_dir=os.path.join(config['testpath'], config['testdataset'], config['reftype']),
    )
    def seed_fn(id):
        np.random.seed()
    test_loader = torch.utils.data.DataLoader(
        test_dataset,
        batch_size=max(1, torch.cuda.device_count()),
        shuffle=False,
        num_workers=config['num_workers'],
        drop_last=True,
        worker_init_fn = seed_fn,
        pin_memory=True
    )
    parallel_model = torch.nn.DataParallel(model)

    # ------------------ predict---------------------
    avg_meter = AverageMeter()
    col = 0
    parallel_model.eval()
    PSNRs = []
    SSIMs = []
    with (torch.no_grad()):
        for features,target in test_loader:
            sdf = features[:,0:3,:,:].cuda()
            illu = features[:,3:6,:,:].cuda()

            start = time.time()
            # compute output
            output = parallel_model(sdf,illu)

            torch.cuda.synchronize()
            end = time.time()
            print("predict time per frame:%.5fs" % (end - start))
            # hook_handle1.remove()
            # hook_handle2.remove()
            # features = features.cpu().numpy()
            noisy_r =  features[:,6:9,:,:].numpy()
            alpha = features[:, 9:, :, :].numpy()
            alpha = np.concatenate((alpha, alpha, alpha), axis=1)
            output = output.cpu().numpy()
            target = target.numpy()

            for i in range(output.shape[0]):
                outputfile = results_save_path+"denoised{}.png".format(col)
                noisyfile = results_save_path+"noisy{}.png".format(col)
                reffile = results_save_path+"ref{}.png".format(col)
                if add_bg == True:
                    bgpath = config['bgpath']
                    bg = cv2.imread(bgpath)
                    bg = resize_image(bg,output[i].shape[1:])
                    # if save_exr == True:
                    #     save_exr_file(output[i],alpha[i],results_save_path+"denoised{}.exr".format(col))
                    writeimage_with_bg(output[i],bg,alpha[i],outputfile,if_sharp=False)
                    writeimage_with_bg(noisy_r[i],bg,alpha[i],noisyfile)
                    writeimage_with_bg(target[i],bg,alpha[i],reffile)
                else:
                    writeimage(output[i], outputfile)
                    writeimage(noisy_r[i], noisyfile)
                    writeimage(target[i], reffile)
                psnr_value, ssim_value = calculate_metrics(output[i], target[i])
                # SSIM, PSNR = ComputeMetrics(output[i],target[i])
                col += 1
                print("PSNR: {}".format(psnr_value))
                print("SSIM: {}".format(ssim_value))
                PSNRs.append(psnr_value)
                SSIMs.append(ssim_value)
    print("Average PSNR: {}".format(sum(PSNRs) / len(PSNRs)))
    print("Average SSIM: {}".format(sum(SSIMs) / len(SSIMs)))


    torch.cuda.empty_cache()


def create_video_from_images(image_folder, output_video='output_video.mp4', fps=8):
    """
    Create a video from a folder of images.

    Parameters:
    - image_folder: Path to the folder containing images.
    - output_video: Filename for the output video.
    - fps: Frames per second in the output video.
    """
    # Get all image files in the folder
    images = [img for img in os.listdir(image_folder) if img.endswith(".png")]
    # Sort images by filename (assuming filenames are sortable for correct order)
    images = sorted(images, key=natural_keys)


    # Get the path of the first image to determine frame size
    frame = cv2.imread(os.path.join(image_folder, images[0]))
    height, width, layers = frame.shape

    # Define the codec and create VideoWriter object
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # Codec used here is for mp4 format
    print(image_folder+output_video)
    video = cv2.VideoWriter(image_folder+output_video, fourcc, fps, (width, height))

    for image in images:
        img = cv2.imread(os.path.join(image_folder, image))
        video.write(img)  # Write the frame to the video

    video.release()  # Release everything when job is finished




if __name__ == '__main__':
    denoise(add_bg = True)
    # result_saved_path = results_save_path + "\\denoised\\b\\"
    # create_video_from_images('E:\\DataSets\\results\\3-dog-8spp\\red-sharp\\')