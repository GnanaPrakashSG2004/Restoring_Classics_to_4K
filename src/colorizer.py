"""Modified implementation of the colorizer from "Deep Colorization", by Cheng et al. (2015)."""

import gc
from typing import Tuple, Union

import torch
from torch import nn, optim
from tqdm import tqdm
from kornia.color import yuv_to_rgb
from kornia.feature import DenseSIFTDescriptor
from kornia.filters import joint_bilateral_blur

class Colorizer(nn.Module):
    """Model that colorizes the grayscale images."""
    def __init__(
            self,
            kernel_size: Union[int, Tuple[int, int]] = 5,
            sigma_color: float = 0.1,
            sigma_space: Union[float, Tuple[float, float]] = 1.5,
        ) -> None:
        super().__init__()

        self.dense_sift = DenseSIFTDescriptor()

        self.conv1 = nn.Conv2d(128, 32, kernel_size=5, stride=1, padding=2)
        self.conv2 = nn.Conv2d(32,   8, kernel_size=3, stride=1, padding=1)
        self.conv3 = nn.Conv2d(8,    2, kernel_size=5, stride=1, padding=2)
        self.relu  = nn.ReLU()

        if isinstance(kernel_size, int):
            kernel_size = (kernel_size, kernel_size)
        self.kernel_size = kernel_size

        self.sigma_color = sigma_color

        if isinstance(sigma_space, float):
            sigma_space = (sigma_space, sigma_space)
        self.sigma_space = sigma_space

    def forward(self, x):
        """Forward pass of the model.

        Args:
            x: The input tensor of shape (batch_size, 1, 270, 512).

        Returns:
            The output tensor of shape (batch_size, 3, 270, 512).
        """
        # original_image represents the luminance values of the image (Y channel)
        original_image = x.clone()

        x = self.dense_sift(x)  # (batch_size, 128, 270, 512)

        x = self.relu(self.conv1(x))  # (batch_size, 16, 270, 512)
        x = self.relu(self.conv2(x))  # (batch_size, 8,  270, 512)
        x = self.conv3(x)             # (batch_size, 2,  270, 512)

        x = joint_bilateral_blur(
            input=x,
            guidance=original_image.repeat(1, 2, 1, 1),
            kernel_size=self.kernel_size,
            sigma_color=self.sigma_color,
            sigma_space=self.sigma_space
        )  # (batch_size, 2, 270, 512)

        # x represents the U and V channels of the image
        u_min, u_max = -0.436, 0.436
        u_channel = x[:, 0].clone()  # (batch_size, 270, 512)
        u_channel = (u_channel - u_channel.min()) / (u_channel.max() - u_channel.min() + 1e-6)
        u_channel = u_channel.clamp(0, 1)
        u_channel = (u_channel * (u_max - u_min) + u_min).unsqueeze(1)  # (batch_size, 1, 270, 512)

        v_min, v_max = -0.615, 0.615
        v_channel = x[:, 1].clone()  # (batch_size, 270, 512)
        v_channel = (v_channel - v_channel.min()) / (v_channel.max() - v_channel.min() + 1e-6)
        v_channel = v_channel.clamp(0, 1)
        v_channel = (v_channel * (v_max - v_min) + v_min).unsqueeze(1)  # (batch_size, 1, 270, 512)

        yuv_image = torch.cat((
            original_image, u_channel, v_channel
        ), dim=1)  # (batch_size, 3, 270, 512)

        rgb_image = yuv_to_rgb(yuv_image)  # (batch_size, 3, 270, 512)
        return rgb_image  # Values in the range [0, 1]

if __name__ == "__main__":
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    LR     = 1e-3

    model = Colorizer().to(DEVICE)
    optimizer = optim.Adam(model.parameters(), lr=LR)

    pbar = tqdm(range(1000))
    for _ in pbar:
        gc.collect()
        torch.cuda.empty_cache()
        optimizer.zero_grad()

        batch = torch.rand(16, 1, 270, 512).to(DEVICE)
        y = model(batch)

        gt = torch.rand(16, 3, 270, 512).to(DEVICE)

        loss = nn.MSELoss()(y, gt)
        pbar.set_postfix_str(f"Loss: {loss.item():.4f}")
        loss.backward()