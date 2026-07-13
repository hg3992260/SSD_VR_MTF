# R_Denoiser: A dual-input lightweight autoencoder for denoising volumatic rendering images

We introduces a novel **real-time** neural denoising technique based on **noisy feature fusion**, tailored for denoising VPT-based DVR. We conduct a detailed analysis of existing neural denoising techniques, revealing their shortcomings in VPT denoising. To better utilize the relationship between the two components, we define a feature decomposition approach, dividing the radiation degree into two parts for separate processing.  Then, we design a dual-input neural network to handle the features of the two parts. We use some acceleration mechanisms to lighten the network, and specially design the decoder part to achieve a balance between lightweight and high precision.

### Network framework

Our network framework is shown as follows.

<img src="images\network.jpg" alt="dog" />

<img src="images\network_details.png" alt="dog" />

### Evaluation

Our model show good performance on Volumatic data, especially in translucent material.

<img src="images\dog.png" alt="dog" style="zoom:50%;" />

### Train and test

The models can be trained following the instruction:

The input data includes 3 channels radiance, 3 channels sdf and 3 channels L. The reference data includes 3 channels radiance.

train:

```bash
python train.py -i /datapath/train/ -o /savepath/log/ -n train_name
```

test:

```bash
python test.py -i /datapath/test/ -o /savepath/log/ -n test_name
```

