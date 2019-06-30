import os
import torch
import numpy as np
import pandas as pd
import SimpleITK as sitk
from torch.utils.data import Dataset, DataLoader
import sklearn

def gamma_correction(img, c, gamma):
    img_array = sitk.GetArrayFromImage(img).astype(np.float32)
    min_value = np.min(img_array)
    max_value = np.max(img_array)    
    img_array = (img_array - min_value) / (max_value - min_value)
    img_array = c * np.power(img_array,gamma)
    img_array = img_array * (max_value - min_value) + min_value
    return img_array


def zero_mean_unit_var(image, mask):
    """Normalizes an image to zero mean and unit variance."""

    img_array = sitk.GetArrayFromImage(image)
    img_array = img_array.astype(np.float32)

    msk_array = sitk.GetArrayFromImage(mask)

    mean = np.mean(img_array[msk_array>0])
    std = np.std(img_array[msk_array>0])

    if std > 0:
        img_array = (img_array - mean) / std
        img_array[msk_array==0] = 0

    image_normalised = sitk.GetImageFromArray(img_array)
    image_normalised.CopyInformation(image)

    return image_normalised


def resample_image(image, out_spacing=(1.0, 1.0, 1.0), out_size=None, is_label=False, pad_value=0):
    """Resamples an image to given element spacing and output size."""

    original_spacing = np.array(image.GetSpacing())
    original_size = np.array(image.GetSize())

    if out_size is None:
        out_size = np.round(np.array(original_size * original_spacing / np.array(out_spacing))).astype(int)
    else:
        out_size = np.array(out_size)

    original_direction = np.array(image.GetDirection()).reshape(len(original_spacing),-1)
    original_center = (np.array(original_size, dtype=float) - 1.0) / 2.0 * original_spacing
    out_center = (np.array(out_size, dtype=float) - 1.0) / 2.0 * np.array(out_spacing)

    original_center = np.matmul(original_direction, original_center)
    out_center = np.matmul(original_direction, out_center)
    out_origin = np.array(image.GetOrigin()) + (original_center - out_center)

    resample = sitk.ResampleImageFilter()
    resample.SetOutputSpacing(out_spacing)
    resample.SetSize(out_size.tolist())
    resample.SetOutputDirection(image.GetDirection())
    resample.SetOutputOrigin(out_origin.tolist())
    resample.SetTransform(sitk.Transform())
    resample.SetDefaultPixelValue(pad_value)

    if is_label:
        resample.SetInterpolator(sitk.sitkNearestNeighbor)
    else:
        resample.SetInterpolator(sitk.sitkBSpline)

    return resample.Execute(image)

def preprocessing(image):
    
    #img_array = gamma_correction(image, 1.8, 2)
    
    img = sitk.DiscreteGaussian(image, 3)
    
    img_array = sitk.GetArrayFromImage(img).astype(np.float32)
    
    img = np.clip(img_array,-1,1).astype(np.float32)
    
    return sitk.GetImageFromArray(img) 


def horizontal_flip(image_array):
    # horizontal flip doesn't need skimage, it's easy as flipping the image array of pixels !
    return image_array[:, ::-1]

def data_augmentation(image):
    
    flipped_image = horizontal_flip(image)
    
    return flipped_image
    

class ImageSegmentationDataset(Dataset):
    """Dataset for image segmentation."""

    def __init__(self, csv_file, img_spacing, img_size):
        """
        Args:
        :param csv_file (string): Path to csv file with image and segmentation filenames.
        """
        print('STARTING CLASS INITIALIZATION')
        self.data = pd.read_csv(csv_file)

        self.samples = []
        self.img_names = []
        self.seg_names = []
        for idx in range(len(self.data)):
            img_path = self.data.iloc[idx, 0]
            seg_path = self.data.iloc[idx, 1]
            msk_path = self.data.iloc[idx, 2]

            print('+ reading image ' + os.path.basename(img_path))
            img = sitk.ReadImage(img_path, sitk.sitkFloat32)

            print('+ reading segmentation ' + os.path.basename(seg_path))
            seg = sitk.ReadImage(seg_path, sitk.sitkInt64)

            print('+ reading mask ' + os.path.basename(msk_path))
            msk = sitk.ReadImage(msk_path, sitk.sitkUInt8)

            #pre=processing
            img = zero_mean_unit_var(img, msk)
            img = resample_image(img, img_spacing, img_size, is_label=False)
            seg = resample_image(seg, img_spacing, img_size, is_label=True)
            msk = resample_image(msk, img_spacing, img_size, is_label=True)
            
            img = preprocessing(img)
            
            print('\n######### processing data augmentation #########')
            
            new_img = data_augmentation(img) #flipping image/mask/segmentation
            new_seg = data_augmentation(seg)
            new_msk = data_augmentation(msk)
            
            print('\n######### data augmentation ended #########')
            
            print("\n out : shape de l'image traitee :", type(img))

            sample = {'img': img, 'seg': seg, 'msk': msk}
            new_sample = {'img': new_img, 'seg': new_seg, 'msk': new_msk}

            self.samples.append(sample)
            self.samples.append(new_sample)
            
            self.img_names.append(os.path.basename(img_path))
            self.seg_names.append(os.path.basename(seg_path))

    def __len__(self):
        return len(self.data)

    def __getitem__(self, item):
        sample = self.samples[item]

        image = torch.from_numpy(sitk.GetArrayFromImage(sample['img'])).unsqueeze(0)
        seg = torch.from_numpy(sitk.GetArrayFromImage(sample['seg'])).unsqueeze(0)
        msk = torch.from_numpy(sitk.GetArrayFromImage(sample['msk'])).unsqueeze(0)

        return {'img': image, 'seg': seg, 'msk': msk}

    def get_sample(self, item):
        return self.samples[item]

    def get_img_name(self, item):
        return self.img_names[item]

    def get_seg_name(self, item):
        return self.seg_names[item]