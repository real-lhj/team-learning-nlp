"""
Logic:
1. AudioDataLoader generate a minibatch from AudioDataset, the size of this
   minibatch is AudioDataLoader's batchsize. For now, we always set
   AudioDataLoader's batchsize as 1. The real minibatch size we care about is
   set in AudioDataset's __init__(...). So actually, we generate the
   information of one minibatch in AudioDataset.
2. After AudioDataLoader getting one minibatch from AudioDataset,
   AudioDataLoader calls its collate_fn(batch) to process this minibatch.
"""
import json

import numpy as np
import torch
import torch.utils.data as data
from utils.utils import IGNORE_ID, pad_list

class AudioDataset(data.Dataset):
    """
    TODO: this is a little HACK now, put batch_size here now.
          remove batch_size to dataloader later.
    """

    def __init__(self, datamfcc_json_path, batch_size, max_length_in, max_length_out,
                 num_batches=0, batch_frames=0):
        # From: espnet/src/asr/asr_utils.py: make_batchset()
        """
        Args:
            data: espnet/espnet json format file.
            num_batches: for debug. only use num_batches minibatch but not all.
        """
        super(AudioDataset, self).__init__()

        with open(datamfcc_json_path, 'r') as f:
            data_mfcc = json.load(f)

        sorted_data_mfcc = sorted(data_mfcc.items(), key=lambda data_mfcc: int(
            data_mfcc[1]['shape'][0]), reverse=True)
        # change batchsize depending on the input and output length
        minibatch = []
        # Method 1: Generate minibatch based on batch_size
        # i.e. each batch contains #batch_size utterances
        if batch_frames == 0:
            start = 0
            while True:
                ilen = int(sorted_data_mfcc[start]['shape'][0])
                olen = int(sorted_data_mfcc[start][1]['output'][0]['shape'][0])
                factor = max(int(ilen / max_length_in), int(olen / max_length_out))
                # if ilen = 1000 and max_length_in = 800
                # then b = batchsize / 2
                # and max(1, .) avoids batchsize = 0
                b = max(1, int(batch_size / (1 + factor)))
                end = min(len(sorted_data_mfcc), start + b)
                minibatch.append(sorted_data_mfcc[start:end])
                # DEBUG
                # total= 0
                # for i in range(start, end):
                #     total += int(sorted_data[i][1]['input'][0]['shape'][0])
                # print(total, end-start)
                if end == len(sorted_data_mfcc):
                    break
                start = end
        # Method 2: Generate minibatch based on batch_frames
        # i.e. each batch contains approximately #batch_frames frames
        else:  # batch_frames > 0
            print("NOTE: Generate minibatch based on batch_frames.")
            print("i.e. each batch contains approximately #batch_frames frames")
            start = 0
            while True:
                total_frames = 0
                end = start
                while total_frames < batch_frames and end < len(sorted_data_mfcc):
                    ilen = int(sorted_data_mfcc[end][1]['shape'][0])
                    total_frames += ilen
                    end += 1
                # print(total_frames, end-start)
                minibatch.append([sorted_data_mfcc[start:end]])
                if end == len(sorted_data_mfcc):
                    break
                start = end
        if num_batches > 0:
            minibatch = minibatch[:num_batches]
        self.minibatch = minibatch

    def __getitem__(self, index):

        return self.minibatch[index]

    def __len__(self):
        return len(self.minibatch)


class AudioDataLoader(data.DataLoader):
    """
    NOTE: just use batchsize=1 here, so drop_last=True makes no sense here.
    """

    def __init__(self, *args, LFR_m=1, LFR_n=1, model_choose='baseline2', **kwargs):
        super(AudioDataLoader, self).__init__(*args, **kwargs)
        self.collate_fn = LFRCollate(LFR_m=LFR_m, LFR_n=LFR_n, model_choose=model_choose)


class LFRCollate(object):
    """Build this wrapper to pass arguments(LFR_m, LFR_n) to _collate_fn"""
    def __init__(self, LFR_m=1, LFR_n=1, model_choose='baseline2'):
        self.LFR_m = LFR_m
        self.LFR_n = LFR_n
        self.model_choose = model_choose


    def __call__(self, batch):
        return _collate_fn(batch, LFR_m=self.LFR_m, LFR_n=self.LFR_n, model_choose=self.model_choose)


# From: espnet/src/asr/asr_pytorch.py: CustomConverter:__call__
def _collate_fn(batch, LFR_m=1, LFR_n=1, model_choose='baseline3'):
    """
    Args:
        batch: list, len(batch) = 1. See AudioDataset.__getitem__()
    Returns:
        xs_pad: N x Ti x D, torch.Tensor
        ilens : N, torch.Tentor
        ys_pad: N x To, torch.Tensor
    """
    # batch should be located in list
    assert len(batch) == 1
    batch = load_inputs_and_targets(batch[0], LFR_m=LFR_m, LFR_n=LFR_n)
    xs, dialect_labels = batch

    import math

    if model_choose in ['baseline2', 'baseline4']:
        ilens = np.array([int(math.ceil(x.shape[0] / 4)) for x in xs])
    else:
        ilens = np.array([int(math.ceil(x.shape[0])) for x in xs])

    # perform padding and convert to tensor
    xs_pad = pad_list([torch.from_numpy(x).float() for x in xs], 0)

    ilens = torch.from_numpy(ilens)

    dialect_labels = torch.from_numpy(dialect_labels)
    return xs_pad, ilens, dialect_labels


# ------------------------------ utils ------------------------------------
def load_inputs_and_targets(batch, LFR_m=1, LFR_n=1):

    label_dict = {'aloe': 0, 'burger': 1, 'cabbage': 2, 'candied_fruits': 3, 'carrots': 4, 'chips':5,
                  'chocolate': 6, 'drinks': 7, 'fries': 8, 'grapes': 9, 'gummies': 10, 'ice-cream':11,
                  'jelly': 12, 'noodles': 13, 'pickles': 14, 'pizza': 15, 'ribs': 16, 'salmon':17,
                  'soup': 18, 'wings': 19}
    label_list = []
    xs = []
    for b in batch[0]:

        if b[0].split('_')[0] == 'candied':
            label_list.append(label_dict[b[0].split('_')[0]+'_fruits'])
        else:
            label_list.append(label_dict[b[0].split('_')[0]])

        npy_dir = b[1]['feat']
        mfcc = np.load(npy_dir)

        xs.append(mfcc)

    if LFR_m != 1 or LFR_n != 1:
        # xs = build_LFR_features(xs, LFR_m, LFR_n)
        xs = [build_LFR_features(x, LFR_m, LFR_n) for x in xs]

    # remove zero-lenght samples
    dialect_labels = np.array(label_list, dtype=np.int64)
    # print('ddd:', xs[0].shape)
    return xs, dialect_labels



def build_LFR_features(inputs, m, n):
    """
    Actually, this implements stacking frames and skipping frames.
    if m = 1 and n = 1, just return the origin features.
    if m = 1 and n > 1, it works like skipping.
    if m > 1 and n = 1, it works like stacking but only support right frames.
    if m > 1 and n > 1, it works like LFR.

    Args:
        inputs_batch: inputs is T x D np.ndarray
        m: number of frames to stack
        n: number of frames to skip
    """
    # LFR_inputs_batch = []
    # for inputs in inputs_batch:
    LFR_inputs = []
    T = inputs.shape[0]
    T_lfr = int(np.ceil(T / n))
    for i in range(T_lfr):
        if m <= T - i * n:
            LFR_inputs.append(np.hstack(inputs[i*n:i*n+m]))
        else: # process last LFR frame
            num_padding = m - (T - i * n)
            frame = np.hstack(inputs[i*n:])
            for _ in range(num_padding):
                frame = np.hstack((frame, inputs[-1]))
            LFR_inputs.append(frame)
    return np.vstack(LFR_inputs)
    #     LFR_inputs_batch.append(np.vstack(LFR_inputs))
    # return LFR_inputs_batch
