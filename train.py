# %% set up environment
import numpy as np
import matplotlib.pyplot as plt
import os
join = os.path.join
from tqdm import tqdm
import torch
from torch.utils.data import Dataset, DataLoader
import monai
from segment_anything import SamPredictor, sam_model_registry
from segment_anything.utils.transforms import ResizeLongestSide
import argparse
# set seeds
torch.manual_seed(2023)
np.random.seed(2023)


#%% create a dataset class to load npz data and return back image embeddings and ground truth
class NpzDataset(Dataset): 
    def __init__(self, data_root, image_size=256):
        self.data_root = data_root
        self.image_size = image_size
        self.npz_files = sorted(os.listdir(self.data_root)) 
        self.npz_data = [np.load(join(data_root, f), allow_pickle = True) for f in self.npz_files]
        # this implementation is ugly but it works (and is also fast for feeding data to GPU) if your server has enough RAM
        # as an alternative, you can also use a list of npy files and load them one by one
        self.ori_gts = np.stack([d['gts'] for d in self.npz_data], axis=0)
        self.img_embeddings = np.stack([d['img_embeddings'] for d in self.npz_data], axis=0)
        print(self.ori_gts.shape, self.img_embeddings.shape)
    
    def __len__(self):
        return self.ori_gts.shape[0]

    def __getitem__(self, index):
        img_embed = self.img_embeddings[index]
        print("img_embed", img_embed.shape)
        img_embed = img_embed.squeeze(0)
        print("img_embed_new", img_embed.shape)
        gt2D = self.ori_gts[index]
        gt2D = gt2D.squeeze(0)
        y_indices, x_indices = np.where(gt2D > 0)
        x_min, x_max = np.min(x_indices), np.max(x_indices)
        y_min, y_max = np.min(y_indices), np.max(y_indices)
        # add perturbation to bounding box coordinates
        
        H, W = gt2D.shape
        x_min = max(0, x_min - np.random.randint(0, 20))

        x_max = min(W, x_max + np.random.randint(0, 20))
        y_min = max(0, y_min - np.random.randint(0, 20))
        y_max = min(H, y_max + np.random.randint(0, 20))
        bboxes = np.array([x_min, y_min, x_max, y_max])
        # con(vert img embedding, mask, bounding box to torch tensor
        #print("img_emb", type(torch.tensor(img_embed)))
        #print("gt2D", type(torch.tensor(gt2D)))
        #print("bboxes", type(torch.tensor(bboxes)))

        return torch.tensor(img_embed).float(), torch.tensor(gt2D[None, :,:].astype(np.int32)).long(), torch.tensor(bboxes).float()


# %% set up parser
parser = argparse.ArgumentParser()
parser.add_argument('-i', '--npz_tr_path', type=str, default='data/Npz_files/output/7/train')
parser.add_argument('--task_name', type=str, default='SAM-ViT-B')
parser.add_argument('--model_type', type=str, default='vit_b')
parser.add_argument('--checkpoint', type=str, default='work_dir/SAM-ViT-B/sam_vit_b_01ec64.pth')
parser.add_argument('--device', type=str, default='cuda:2')
parser.add_argument('--work_dir', type=str, default='./work_dir')
# 
parser.add_argument('--num_epochs', type=int, default=300)
parser.add_argument('--batch_size', type=int, default=8)
parser.add_argument('--lr', type=float, default=1e-5)
parser.add_argument('--weight_decay', type=float, default=0)
args = parser.parse_args()


# %% set up model for fine-tuning 
device = args.device
model_save_path = join(args.work_dir, args.task_name)
os.makedirs(model_save_path, exist_ok=True)
sam_model = sam_model_registry[args.model_type](checkpoint=args.checkpoint).to(device)
sam_model.train()

# Set up the optimizer, hyperparameter tuning will improve performancƒe here
optimizer = torch.optim.Adam(sam_model.mask_decoder.parameters(), lr=args.lr, weight_decay=args.weight_decay)
seg_loss = monai.losses.DiceCELoss(sigmoid=True, squared_pred=True, reduction='mean')
# regress loss for IoU/DSC prediction; (ignored for simplicity but will definitely included in the near future)
# regress_loss = torch.nn.MSELoss(reduction='mean')
#%% train
num_epochs = args.num_epochs
losses = []
best_loss = 1e10
train_dataset = NpzDataset(args.npz_tr_path)
train_dataloader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
for epoch in range(num_epochs):
    epoch_loss = 0
    # Just train on the first 20 examples
    for step, (image_embedding, gt2D, boxes) in enumerate(tqdm(train_dataloader)):
        # do not compute gradients for image encoder and prompt encoder
        with torch.no_grad():
            # convert box to 1024x1024 grid
            box_np = boxes.numpy()
            sam_trans = ResizeLongestSide(sam_model.image_encoder.img_size)
            box = sam_trans.apply_boxes(box_np, (gt2D.shape[-2], gt2D.shape[-1]))
            box_torch = torch.as_tensor(box, dtype=torch.float, device=device)
            if len(box_torch.shape) == 2:
                box_torch = box_torch[:, None, :] # (B, 1, 4)
            
            sparse_embeddings, dense_embeddings = sam_model.prompt_encoder(
                points=None,
                boxes=box_torch,
                masks=None,
            )
        print("image_embeddings", image_embedding.shape)
        low_res_masks, iou_predictions = sam_model.mask_decoder(
            image_embeddings=image_embedding.to(device), # (B, 256, 64, 64)
            image_pe=sam_model.prompt_encoder.get_dense_pe(), # (1, 256, 64, 64)
            sparse_prompt_embeddings=sparse_embeddings, # (B, 2, 256)
            dense_prompt_embeddings=dense_embeddings, # (B, 256, 64, 64)
            multimask_output=True,
          )

        loss = seg_loss(low_res_masks, gt2D.to(device))
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        epoch_loss += loss.item()
    epoch_loss /= step
    losses.append(epoch_loss)
    print(f'EPOCH: {epoch}, Loss: {epoch_loss}')
    # save the model checkpoint
    torch.save(sam_model.state_dict(), join(model_save_path, 'sam_model_latest_7.pth'))
    # save the best model
    if epoch_loss < best_loss:
        best_loss = epoch_loss
        torch.save(sam_model.state_dict(), join(model_save_path, 'sam_model_best_7.pth'))

    # %% plot loss
    plt.plot(losses)
    plt.title('Dice + Cross Entropy Loss')
    plt.xlabel('Epoch')
    plt.ylabel('Loss')
    # plt.show() # comment this line if you are running on a server
    plt.savefig(join(model_save_path, 'train_loss_7.png'))
    plt.close()

