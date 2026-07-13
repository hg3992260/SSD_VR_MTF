import torch.utils.data
import os
from tools.prepare_data import *
import hashlib
import tempfile
import h5py
import tqdm
import atexit
from multiprocessing.pool import ThreadPool

os.environ['TMP'] = 'D:\\DataSets\\volumndatasets\\Temp\\'
os.environ['TMPDIR'] = 'D:\\DataSets\\volumndatasets\\Temp\\'
os.environ['TEMP'] = 'D:\\DataSets\\volumndatasets\\Temp\\'
TILE_SIZE = 512
N_FRAMES = 1 # number of previous AND subsequent frames, i.e. (2*N_FRAMES)+1 in total
pool = ThreadPool(os.cpu_count())
atexit.register(pool.join)
atexit.register(pool.close)
# 用哈希创建了一个不会重复的缓存文件，用来存储数据
def cache_path(path, ext):
    name = hashlib.md5(path.encode()).hexdigest()
    # 默认存在了 C:\Users\hitic\AppData\Local\Temp\dl-cache
    cache = os.path.join(os.path.join(tempfile.gettempdir(), 'dl-cache'), name)
    # cache = os.path.join(os.path.join(os.path.dirname(__file__), '../data-cache'), name)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    return os.path.splitext(cache)[0] + ext
def glob_directory(directory, key, filter_feature_maps=True):
    in_files = (os.path.join(directory, x) for x in os.listdir(directory))
    in_files = filter(lambda x: key in x, in_files)
    if filter_feature_maps:
        in_files = filter(lambda x: '_pos' not in os.path.basename(x), in_files)
        in_files = filter(lambda x: '_norm' not in os.path.basename(x), in_files)
        in_files = filter(lambda x: '_alb' not in os.path.basename(x), in_files)
        in_files = filter(lambda x: '_vol' not in os.path.basename(x), in_files)

    return sorted(list(in_files),key=natural_keys)
def glob_directory_recursive(directory, key, filter_feature_maps):
    files = glob_directory(directory, key, filter_feature_maps)
    for root, dirs, _ in os.walk(directory):
        for name in sorted(dirs):
            d = os.path.join(root, name)
            files.extend(glob_directory(d, key, filter_feature_maps))
    return files
def _load_radiance(filename):
    # img = imageio.imread(filename)
    # if img.dtype == 'float32' or img.dtype == 'float64':
    #     img = np.round(np.clip(img, 0, 1) * 255).astype('uint8')
    # elif img.dtype == 'uint16':
    #     img = np.round(255 * img.astype('float32') / 65535).astype('uint8')
    # assert img.dtype == 'uint8', "Unhandled image data type!"
    # return np.transpose(img, [2, 0, 1]) # to channels first
    # 改成读exr数据
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

    channel_datas = np.round(np.clip(channel_datas, 0, 1) * 255).astype('uint8')
    # channel_datas = channel_datas.transpose(2,0,1)
    return channel_datas

def _load_f_l(filename):
    exr_file = OpenEXR.InputFile(filename)
    header = exr_file.header()

    channel_names = [ "SingleRadiDividedBySdf_B", "SingleRadiDividedBySdf_G", "SingleRadiDividedBySdf_R", "Sdf_B", "Sdf_G", "Sdf_R"]
    channel_datas = []
    for channelname in channel_names:
        half_channel = exr_file.channel(channelname, Imath.PixelType(Imath.PixelType.HALF))
        width = header['dataWindow'].max.x - header['dataWindow'].min.x + 1
        height = header['dataWindow'].max.y - header['dataWindow'].min.y + 1
        half_array = np.frombuffer(half_channel, dtype=np.float16)
        half_array = np.reshape(half_array, (height, width))
        channel_datas.append(half_array)
    channel_datas = np.array(channel_datas)

    channel_datas = np.round(np.clip(channel_datas, 0, 1) * 255).astype('uint8')
    return channel_datas


def _load_all(filename):
    exr_file = OpenEXR.InputFile(filename)
    header = exr_file.header()

    channel_names = ["SingleRadiDividedBySdf_B", "SingleRadiDividedBySdf_G", "SingleRadiDividedBySdf_R",
                     "Sdf_B", "Sdf_G", "Sdf_R","SingleRadi_B", "SingleRadi_G", "SingleRadi_R", "Alpha"]
    channel_datas = []
    for channelname in channel_names:
        half_channel = exr_file.channel(channelname, Imath.PixelType(Imath.PixelType.HALF))
        width = header['dataWindow'].max.x - header['dataWindow'].min.x + 1
        height = header['dataWindow'].max.y - header['dataWindow'].min.y + 1
        half_array = np.frombuffer(half_channel, dtype=np.float16)
        half_array = np.reshape(half_array, (height, width))
        channel_datas.append(half_array)
    channel_datas = np.array(channel_datas)

    channel_datas = np.round(np.clip(channel_datas, 0, 1) * 255).astype('uint8')
    return channel_datas
def _load_image_internal(filename,imgtype):
    """ load rgb image file from disk with feature maps and return numpy array with shape (c, h, w) """
    if imgtype == 0:
        img = _load_f_l(filename)
    elif imgtype == 1:
        img = _load_radiance(filename)
    else:
        img = _load_all(filename)
    return img


def preprocess_image(x):

    # convert to float32
    if x.dtype == 'uint8':
        x = x.astype('float32') * (1/255)
    # elif x.dtype == 'uint16':
    #     x = x.astype('float32') * (1/65535)
    # elif x.dtype == 'float64':
    #     x = x.astype('float32')
    # elif x.dtype == 'float32':
    #     x = x
    # else:
    #     raise ValueError('Unkown image data type')
    # clip and gamma adjust
    x = np.clip(x, 0, 1)
    # x[..., 0:3, :, :] = np.square(x[..., 0:3, :, :])
    return x

def make_dataset(directory, isnoise, key='.exr'):
    # 有个问题，同一个路径下的都一样，我需要从不同路径下得到bg和noisy radiance的数据
    filename = cache_path(directory, '.h5')
    print(filename)
    if not os.path.isfile(filename):
        print(f'Building dataset from {directory} -> {filename} (this may take a while)...')
        with h5py.File(filename, 'w') as f:
            files = glob_directory_recursive(directory, key=key, filter_feature_maps=False)
            assert len(files) > 0, "Dataset is empty!"
            # load single image to determine shape
            tmp = _load_image_internal(files[0],isnoise)
            shape = (len(files), tmp.shape[-3], tmp.shape[-2], tmp.shape[-1])

            # create dataset and load fill with images
            dset = f.create_dataset('data', shape=shape, dtype=tmp.dtype)
            tq = tqdm.tqdm(total=len(files))
            def helper(dset, idx, f):
                dset[idx] = _load_image_internal(f,isnoise)
                tq.update(1)
            pool.starmap(lambda i, f: helper(dset, i, f), enumerate(files))
            tq.close()
    return h5py.File(filename, 'r')['data']

class DataSetTrain(torch.utils.data.Dataset):
    def __init__(self, img_dir, ref_dir, transform=None):
    # def __init__(self, dir_x, dir_y, features=[]):
        print(f'Loading train dataset from {img_dir} and {ref_dir}...')
        self.data_x = make_dataset(img_dir,0)
        self.data_y = make_dataset(ref_dir,1)
        assert self.data_x.shape[-2:0] == self.data_y.shape[-2:0], "Data set size mismatch!"
        assert len(self.data_x) == len(self.data_y), "Data set length mismatch!"
        # self.features = [(features[2*i], features[2*i+1]) for i in range(len(features)//2)]
        self.input_channels = self.data_x.shape[-3]


    def __len__(self):
        return 4 * len(self.data_x) # ~4 random crops per image per epoch

    def __getitem__(self, idx):
        # 在idx序列里随机取元素
        f = np.random.randint(0, len(self.data_x))
        # x起始位置
        # y起始位置
        from_x = np.random.randint(0, self.data_x.shape[-1] - TILE_SIZE)
        from_y = np.random.randint(0, self.data_x.shape[-2] - TILE_SIZE)

        # 从h5里取data的方式，但是它的tilesize是256？不知道后面怎么弄大
        x = self.data_x[f, :, from_y:from_y+TILE_SIZE, from_x:from_x+TILE_SIZE]
        y = self.data_y[f, :, from_y:from_y+TILE_SIZE, from_x:from_x+TILE_SIZE]


        return preprocess_image(x.copy()), preprocess_image(y.copy())

# val用别的数据
class DataSetVal(torch.utils.data.Dataset):
    def __init__(self, img_dir, ref_dir, transform=None):
    # def __init__(self, dir_x, dir_y, features=[]):
        print(f'Loading val dataset from {img_dir} and {ref_dir}...')
        self.data_x = make_dataset(img_dir,0)
        self.data_y = make_dataset(ref_dir,1)
        assert self.data_x.shape[-2:0] == self.data_y.shape[-2:0], "Data set size mismatch!"

        assert len(self.data_x) == len(self.data_y), "Data set length mismatch!"
        self.input_channels = self.data_x.shape[-3]


    def __len__(self):
        return len(self.data_x) # ~4 random crops per image per epoch

    def __getitem__(self, idx):
        x, y = self.data_x[idx, ...], self.data_y[idx, ...]

        pad_h = 2048 - x.shape[1]
        pad_w = 2048 - x.shape[2]
        x = resize_img(x, 2048)
        y = resize_img(y, 2048)

        return preprocess_image(x), preprocess_image(y)
def resize_img(image,target_size):
    """
    Resize the image to target_size x target_size by padding or cropping.

    Parameters:
        image (numpy.ndarray): The input image array of shape (channels, width, height).
        target_size (int): The target size for width and height (default is 2048).

    Returns:
        numpy.ndarray: The resized image of shape (channels, target_size, target_size).
    """
    channels, width, height = image.shape
    # Initialize the output image with the original image
    output_image = image
    # Check width and height and crop or pad accordingly
    if width > target_size:
        # Crop width
        start_x = (width - target_size) // 2
        output_image = output_image[:, start_x:start_x + target_size, :]
    elif width < target_size:
        # Pad width
        pad_width = (target_size - width) // 2
        pad_width_remainder = (target_size - width) % 2
        output_image = np.pad(output_image, ((0, 0), (pad_width, pad_width + pad_width_remainder), (0, 0)),
                              mode='constant')

    # Update width after potential cropping/padding
    _, new_width, _ = output_image.shape
    if height > target_size:
        # Crop height
        start_y = (height - target_size) // 2
        output_image = output_image[:, :, start_y:start_y + target_size]
    elif height < target_size:
        # Pad height
        pad_height = (target_size - height) // 2
        pad_height_remainder = (target_size - height) % 2
        output_image = np.pad(output_image, ((0, 0), (0, 0), (pad_height, pad_height + pad_height_remainder)),
                              mode='constant')
    return output_image
class DataSetPredict(torch.utils.data.Dataset):
    def __init__(self, img_dir, ref_dir):
        # predict的x通道包括：[前六个是sdf和L，中间三个是radiance，后面三个是bg，最后一个是alpha]
        self.data_x = make_dataset(img_dir, 2)
        self.data_y = make_dataset(ref_dir, 1)
        # 都要编码成uint8才能放到h5里面
        self.input_channels = self.data_x.shape[-3]


    def __len__(self):
        return  len(self.data_x)  # ~4 random crops per image per epoch

    def __getitem__(self, idx):
        x= self.data_x[idx, ...]
        y = self.data_y[idx, ...]
        pad_h = 2048 - x.shape[1]
        pad_w = 2048 - x.shape[2]
        x = resize_img(x,2048)
        y = resize_img(y, 2048)
        # x = np.pad(x, ((0, 0), (0, pad_h), (0, pad_w)), mode='constant', constant_values=0)
        # y = np.pad(y, ((0, 0), (0, pad_h), (0, pad_w)), mode='constant', constant_values=0)

        return preprocess_image(x),preprocess_image(y)


class Dataset(torch.utils.data.Dataset):
    def __init__(self, img_ids, img_dir, ref_dir, transform=None):
        self.img_ids = img_ids
        self.img_dir = img_dir
        self.ref_dir = ref_dir
        self.transform = transform
    def __len__(self):
        return len(self.img_ids)

    def __getitem__(self, idx):


        img_id = self.img_ids[idx]
        sdf = get_sdf(os.path.join(self.img_dir, img_id+".exr"))
        illu = get_illu(os.path.join(self.ref_dir, img_id+".exr"))
        ref = get_volumn_radiance(os.path.join(self.ref_dir, img_id+".exr"))
        img = np.concatenate((sdf, illu), axis=2)
        img = img.astype('float32')
        ref = ref.astype('float32')
        if self.transform is not None:
            augmented = self.transform(image=img, mask=ref)
            img = augmented['image']
            ref = augmented['mask']
        img = img.transpose(2, 0, 1)
        ref = ref.transpose(2, 0, 1)
        alpha =  np.concatenate((img[-1:,:,:], img[-1:,:,:],img[-1:,:,:]), axis=0)
        return img[0:3,:,:], img[3:6,:,:],ref
