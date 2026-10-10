import torch
import torchvision.transforms as T
from PIL import Image
import numpy as np
import logging

logger = logging.getLogger("hackcure.transformer")

class TransformerFeatureExtractor:
    """
    Isolated module to load DINOv2 and extract features from patient crops.
    This acts as the bridge between YOLO spatial detection and temporal risk prediction.
    """
    def __init__(self, model_size='vits14', device=None):
        self.device = device if device else ('cuda' if torch.cuda.is_available() else 'cpu')
        self.model_name = f'dinov2_{model_size}'
        logger.info(f"Loading {self.model_name} on {self.device}...")
        
        # Load DINOv2 from torch hub
        self.model = torch.hub.load('facebookresearch/dinov2', self.model_name)
        self.model = self.model.to(self.device)
        self.model.eval()
        
        # Standard ImageNet transform for ViT
        self.transform = T.Compose([
            T.Resize((224, 224)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        logger.info("Transformer backbone loaded successfully.")

    @torch.no_grad()
    def extract_features(self, image_crop):
        """
        Extracts features from an image crop (numpy array or PIL image).
        
        Args:
            image_crop: RGB image of the patient (from YOLO bounding box)
            
        Returns:
            dict containing class token and patch tokens
        """
        if isinstance(image_crop, np.ndarray):
            image_crop = Image.fromarray(image_crop)
            
        img_tensor = self.transform(image_crop).unsqueeze(0).to(self.device)
        
        # Get dense features
        ret = self.model.forward_features(img_tensor)
        
        cls_token = ret['x_norm_clstoken'].cpu().numpy().squeeze()
        patch_tokens = ret['x_norm_patchtokens'].cpu().numpy().squeeze()
        
        return {
            "cls_token": cls_token,         # (384,) for ViT-S
            "patch_tokens": patch_tokens    # (256, 384) for ViT-S at 224x224
        }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Testing Transformer Prototype...")
    
    # Create a dummy image for testing
    dummy_img = np.random.randint(0, 255, (300, 300, 3), dtype=np.uint8)
    
    try:
        extractor = TransformerFeatureExtractor()
        features = extractor.extract_features(dummy_img)
        logger.info(f"Successfully extracted features.")
        logger.info(f"CLS token shape: {features['cls_token'].shape}")
        logger.info(f"Patch tokens shape: {features['patch_tokens'].shape}")
    except Exception as e:
        logger.error(f"Failed to load or run transformer: {e}")
