# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/core.ipynb.

# %% ../nbs/core.ipynb 3
from __future__ import annotations
import numpy as np
from typing import Callable, Union, List, Tuple, Dict, Any, Optional, TypeVar, Generic, Iterable, Sequence, Iterator
import jax
from jax import vmap, grad, jit, numpy as jnp
from jax.random import PRNGKey
from abc import ABC
from dataclasses import dataclass
import collections

# %% auto 0
__all__ = ['PRNGSequence', 'Dataset', 'BaseDataLoader', 'DataLoaderJax', 'DataLoaderPytorch', 'DataloaderBackends', 'DataLoader']

# %% ../nbs/core.ipynb 4
try: import torch.utils.data as torch_data
except ModuleNotFoundError: torch_data = None

try: import haiku as hk 
except ModuleNotFoundError: hk = None

# %% ../nbs/core.ipynb 5
@dataclass
class Config:
    rng_reserve_size: int
    global_seed: int

    @classmethod
    def default(cls) -> Config:
        return cls(rng_reserve_size=1, global_seed=42)

# %% ../nbs/core.ipynb 6
main_config = Config.default()

# %% ../nbs/core.ipynb 7
def get_config() -> Config:
    return main_config

# %% ../nbs/core.ipynb 8
class PRNGSequence(Iterator[PRNGKey]):
    """An Interator of Jax PRNGKey (minimal version of haiku.PRNGSequence)."""

    def __init__(self, seed: int):
        self._key = jax.random.PRNGKey(seed)
        self._subkeys = collections.deque()

    def reserve(self, num):
        """Splits additional ``num`` keys for later use."""
        if num > 0:
            new_keys = tuple(jax.random.split(self._key, num + 1))
            self._key = new_keys[0]
            self._subkeys.extend(new_keys[1:])
            
    def __next__(self):
        if not self._subkeys:
            self.reserve(get_config().rng_reserve_size)
        return self._subkeys.popleft()

# %% ../nbs/core.ipynb 9
class Dataset:
    """A simple pytorch-like Numpy Dataset."""
    
    def __init__(self, *arrays: jnp.DeviceArray):
        assert all(arrays[0].shape[0] == arr.shape[0] for arr in arrays), \
            "All arrays must have the same dimension."
        self.arrays = arrays

    def __len__(self):
        return self.arrays[0].shape[0]

    def __getitem__(self, idx):
        return tuple(arr[idx] for arr in self.arrays)

# %% ../nbs/core.ipynb 13
class BaseDataLoader(ABC):
    """Dataloader Interface"""
    def __init__(
        self, 
        dataset,
        batch_size: int = 1,  # batch size
        shuffle: bool = False,  # if true, dataloader shuffles before sampling each batch
        drop_last: bool = False,
        **kwargs
    ):
        pass 
    
    def __len__(self):
        raise NotImplementedError
    
    def __next__(self):
        raise NotImplementedError
    
    def __iter__(self):
        raise NotImplementedError

# %% ../nbs/core.ipynb 15
class DataLoaderJax(BaseDataLoader):
    """Dataloder in Vanilla Jax"""

    def __init__(
        self, 
        dataset: Dataset,
        batch_size: int = 1,  # batch size
        shuffle: bool = False,  # if true, dataloader shuffles before sampling each batch
        drop_last: bool = False, # drop last batches or not
        **kwargs
    ):
        self.dataset = dataset
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.drop_last = drop_last

        self.keys = PRNGSequence(seed=get_config().global_seed) \
            if hk is None else hk.PRNGSequence(get_config().global_seed)
        self.data_len = len(dataset)  # Length of the dataset
        self.indices = jnp.arange(self.data_len) # available indices in the dataset
        self.pose = 0  # record the current position in the dataset
        self._shuffle()

    def _shuffle(self):
        if self.shuffle:
            self.indices = jax.random.permutation(next(self.keys), self.indices)
        
    def _stop_iteration(self):
        self.pose = 0
        self._shuffle()
        raise StopIteration

    def __len__(self):
        if self.drop_last:
            batches = len(self.dataset) // self.batch_size  # get the floor of division
        else:
            batches = -(len(self.dataset) // -self.batch_size)  # get the ceil of division
        return batches

    def __next__(self):
        if self.pose + self.batch_size <= self.data_len:
            batch_indices = self.indices[self.pose: self.pose + self.batch_size]
            batch_data = self.dataset[batch_indices, ...]
            self.pose += self.batch_size
            return batch_data
        elif self.pose < self.data_len and not self.drop_last:
            batch_indices = self.indices[self.pose:]
            batch_data = self.dataset[batch_indices, ...]
            self.pose += self.batch_size
            return batch_data
        else:
            self._stop_iteration()

    def __iter__(self):
        return self

# %% ../nbs/core.ipynb 19
# copy from https://jax.readthedocs.io/en/latest/notebooks/Neural_Network_and_Data_Loading.html#data-loading-with-pytorch
def _numpy_collate(batch):
    if isinstance(batch[0], np.ndarray):
        return np.stack(batch)
    elif isinstance(batch[0], (tuple, list)):
        transposed = zip(*batch)
        return [_numpy_collate(samples) for samples in transposed]
    else:
        return np.array(batch)

def _convert_dataset_pytorch(dataset: Dataset):
    class DatasetPytorch(torch_data.Dataset):
        def __init__(self, dataset: Dataset): self.dataset = dataset
        def __len__(self): return len(self.dataset)
        def __getitem__(self, idx): return self.dataset[idx]
    
    return DatasetPytorch(dataset)

# %% ../nbs/core.ipynb 20
class DataLoaderPytorch(BaseDataLoader):
    """Pytorch Dataloader"""
    def __init__(
        self, 
        dataset: Dataset,
        batch_size: int = 1,  # batch size
        shuffle: bool = False,  # if true, dataloader shuffles before sampling each batch
        drop_last: bool = False, # drop last batch or not
        **kwargs
    ):
        if torch_data is None:
            raise ModuleNotFoundError("`pytorch` library needs to be installed. Try `pip install torch`."
            "Please refer to pytorch documentation for details: https://pytorch.org/get-started/.")
        
        dataset = _convert_dataset_pytorch(dataset)
        self.dataloader = torch_data.DataLoader(
            dataset, 
            batch_size=batch_size, 
            shuffle=shuffle, 
            drop_last=drop_last,
            collate_fn=_numpy_collate,
            **kwargs
        ) 

    def __len__(self):
        return len(self.dataloader)

    def __next__(self):
        return next(self.dataloader)

    def __iter__(self):
        return self.dataloader.__iter__()

# %% ../nbs/core.ipynb 23
@dataclass(frozen=True)
class DataloaderBackends:
    jax: BaseDataLoader = DataLoaderJax
    pytorch: BaseDataLoader = DataLoaderPytorch
    tensorflow: BaseDataLoader = None
    merlin: BaseDataLoader = None

    __all__ = dict(
        jax=jax, pytorch=pytorch, tensorflow=tensorflow, merlin=merlin
    )

    def __getitem__(self, key):
        return self.__all__[key]

    @property
    def supported(self) -> List[str]:
        return [
            backend for backend, dl_cls in self.__all__.items() if dl_cls is not None
        ]

# %% ../nbs/core.ipynb 24
def _dispatch_dataloader(
    backend: str # dataloader backend
) -> BaseDataLoader:
    """Return Dataloader class based on given `backend`"""
    backends = DataloaderBackends()
    if not backend in backends.supported:
        raise ValueError(f"backend=`{backend}` is either an invalid backend or not supported yet. "
            f"Should be one of {backends.supported}.")
    
    dl_cls = backends[backend]
    return dl_cls


# %% ../nbs/core.ipynb 26
class DataLoader:
    """Main Dataloader class to load Numpy data batches"""
    def __init__(
        self,
        dataset: Dataset,
        backend: str, # Dataloader backend
        batch_size: int = 1,  # batch size
        shuffle: bool = False,  # if true, dataloader shuffles before sampling each batch
        drop_last: bool = False, # drop last batches or not
        **kwargs
    ):
        dataloader_cls = _dispatch_dataloader(backend)
        self.dataloader = dataloader_cls(
            dataset=dataset, 
            batch_size=batch_size, 
            shuffle=shuffle, 
            drop_last=drop_last,
            **kwargs
        )

    def __len__(self):
        return len(self.dataloader)

    def __next__(self):
        return next(self.dataloader)

    def __iter__(self):
        return self.dataloader.__iter__()
