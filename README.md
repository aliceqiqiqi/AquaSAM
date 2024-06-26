# AquaSAM
This repository is the official PyTorch implementation of AquaSAM: Foreground Underwater Image Segmentation.([arxiv](https://arxiv.org/abs/2308.04218)). 
AquaSAM is the first attempt to extend the success of segment-anything model in the domains of underwater images.
## Installation
1. Install [Pytorch 2.0](https://pytorch.org/get-started/locally/)
2. `git clone https://github.com/duooppa/AquaSAM`
3. Enter the AquaSAM folder `cd AquaSAM` and run `pip install -e .`


## Fine-tune SAM on customized dataset

We provide a step-by-step tutorial with a SUIM dataset to help you quickly start the training process.

### Data preparation and preprocessing

Download [SAM checkpoint](https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth) and place it at `work_dir/SAM/sam_vit_b_01ec64.pth` .

Download the demo [dataset](https://zenodo.org/record/7860267) and unzip.

In this tutorial, we will fine-tune SAM for foreground underwater image segmentation.

Run pre-processing

```bash
python pre_mbl.py
```
- split dataset: 80% for training and 20% for testing
- image normalization
- pre-compute image embedding

### Model Training

Please check the step-by-step tutorial: `train.py`.

You can also train the model on the whole dataset. 
Download the training set (https://irvlab.cs.umn.edu/resources/suim-dataset)
