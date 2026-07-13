import argparse
def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument('--name', default="4-artifix-8spp",
                        help='model name: (default: arch+timestamp)')
    parser.add_argument('--testname', default="4-artifix-8spp",
                        help='model name: (default: arch+timestamp)')
    parser.add_argument('--epochs', default=100, type=int, metavar='N',
                        help='number of total epochs to run')
    parser.add_argument('-b', '--batch_size', default=4, type=int,
                        metavar='N', help='mini-batch size (default: 16)')
    parser.add_argument('-t', '--time_consider', default=3, type=int,
                        metavar='N', help='time_consider')
    # # model
    # parser.add_argument('--input_w', default=256, type=int,
    #                     help='image width')
    # parser.add_argument('--input_h', default=256, type=int,
    #                     help='image height')

    # dataset
    # train
    parser.add_argument('--dataset', default='4-artifix/',
                        help='dataset name')
    parser.add_argument('--trainpath', default='D://DataSets//volumndatasets//0614//train//',
                        help='dataset path')
    parser.add_argument('--valpath', default='D://DataSets//volumndatasets//0614//val//',
                        help='dataset path')
    parser.add_argument('--noisetype', default='8spp',
                        help='noisetype')
    parser.add_argument('--reftype', default='512spp',
                        help='reftype')
    # test
    parser.add_argument('--testdataset', default='4-artifix//',
                        help='dataset name')
    parser.add_argument('--testpath', default='D://DataSets//volumndatasets//0614//test//',
                        help='dataset path')
    parser.add_argument('--bgpath', '--background_path', default='D:\\DataSets\\volumndatasets\\background\\bg2.png',
                        help='add background')
    # optimizer
    parser.add_argument('--lr', '--learning_rate', default=1e-4, type=float,
                        metavar='LR', help='initial learning rate')
    parser.add_argument('--min_lr', default=1e-5, type=float,
                        help='minimum learning rate')
    parser.add_argument('--momentum', default=0.9, type=float,
                        help='momentum')
    parser.add_argument('--weight_decay', default=1e-4, type=float,
                        help='weight decay')

    parser.add_argument('--num_workers', default=0, type=int)

    config = parser.parse_args()

    return config