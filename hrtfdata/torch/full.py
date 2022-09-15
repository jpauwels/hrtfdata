from ..datapoint import DataPoint, SofaSphericalDataPoint, CipicDataPoint, AriDataPoint, ListenDataPoint, BiLiDataPoint, ItaDataPoint, HutubsDataPoint, RiecDataPoint, ChedarDataPoint, WidespreadDataPoint, Sadie2DataPoint, ThreeDThreeADataPoint, SonicomDataPoint
import warnings
from pathlib import Path
from typing import Any, Callable, List, Iterable, Optional, TypeVar, Dict, IO, Tuple, Iterator
import numpy as np
from PIL.Image import Image, LANCZOS
from torch.utils.data import Dataset as TorchDataset
from torchvision.transforms import ToTensor
# from torchvision.datasets.utils import check_integrity, download_and_extract_archive
import numpy as np


def _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec):
    spec_list = [spec for spec in (feature_spec, target_spec, group_spec) if spec is not None]
    hrir_spec = {k: v for d in spec_list for k, v in d.items()}.get('hrirs', {})
    return hrir_spec.get('samplerate'), hrir_spec.get('length')
    

class HRTFDataset(TorchDataset):

    def __init__(
        self,
        datapoint: DataPoint,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        image_transform: Optional[Callable] = ToTensor(),
        measurement_transform: Optional[Callable] = None,
        hrir_transform: Optional[Callable] = None,
        # download: bool = True,
    ) -> None:
        super().__init__()#root, transform=transform, target_transform=target_transform) # torchvision dataset
        self._image_transform = image_transform
        self._measurement_transform = measurement_transform
        self._hrir_transform = hrir_transform
        self._query = datapoint.query
        # Allow specifying ids that are excluded by default without explicitly overriding `exclude_ids``
        if subject_ids is not None and not isinstance(subject_ids, str) and exclude_ids is None:
            exclude_ids = ()
        self._exclude_ids = exclude_ids

        if target_spec is None:
            target_spec = {}
        if group_spec is None:
            group_spec = {}

        self._specification = {**feature_spec, **target_spec, **group_spec}
        if not self._specification:
            raise ValueError('At least one specification should not be empty')
        if subject_requirements is not None:
            self._specification = {**self._specification, **subject_requirements}
        ear_ids = self._query.specification_based_ids(self._specification, include_subjects=subject_ids, exclude_subjects=exclude_ids)

        if len(ear_ids) == 0:
            if len(self._query.specification_based_ids(self._specification)) == 0:
                raise ValueError('Empty dataset. Check if its configuration and paths are correct.')
            self.subject_ids = tuple()
            self.hrir_samplerate = None
            self.hrtf_frequencies = None
            self._features = []
            self._targets = []
            self._groups = []
            self._selected_angles = {}
            self.row_angles = np.array([])
            self.column_angles = np.array([])
            return

        self.subject_ids, self.sides = zip(*ear_ids)

        if 'hrirs' in self._specification.keys():
            self._selected_angles, row_indices, column_indices = datapoint.hrir_angle_indices(
                self.subject_ids[0],
                self._specification['hrirs'].get('row_angles'),
                self._specification['hrirs'].get('column_angles')
            )
            self.row_angles = np.array(list(self._selected_angles.keys()))
            self.column_angles = np.ma.getdata(list(self._selected_angles.values())[0])
            side = self._specification['hrirs'].get('side', '')
            if side.startswith('both-'):
                if isinstance(datapoint, SofaSphericalDataPoint):
                    # mirror azimuths/rows
                    start_idx = 1 if np.isclose(self.row_angles[0], -180) else 0
                    if not np.allclose(self.row_angles[start_idx:], -np.flip(self.row_angles[start_idx:])):
                        raise ValueError(f'Only datasets with symmetric azimuths can use {side} sides.')
                else:
                    # mirror laterals/columns
                    if not np.allclose(self.column_angles, -np.flip(self.column_angles)):
                        raise ValueError(f'Only datasets with symmetric lateral angles can use {side} sides.')
                
        else:
            self._selected_angles = {}
            self.row_angles = np.array([])
            self.column_angles = np.array([])


        self.hrir_samplerate = datapoint.hrir_samplerate(self.subject_ids[0])
        self.hrir_length = datapoint.hrir_length(self.subject_ids[0])
        self.hrtf_frequencies = datapoint.hrtf_frequencies(self.subject_ids[0])

        self._features: Any = []
        self._targets: Any = []
        self._groups: Any = []
        for subject, side in ear_ids:
            for spec, store in (feature_spec, self._features), (target_spec, self._targets), (group_spec, self._groups):
                subject_data = {}
                if 'images' in spec.keys():
                    subject_data['images'] = datapoint.pinna_image(subject, side=side, rear=spec['images'].get('rear', False))
                if 'anthropometry' in spec.keys():
                    subject_data['anthropometry'] = datapoint.anthropomorphic_data(subject, side=side, select=spec['anthropometry'].get('select', None))
                if 'hrirs' in spec.keys():
                    subject_data['hrirs'] = datapoint.hrir(subject, side=side, domain=spec['hrirs'].get('domain', 'time'), row_indices=row_indices, column_indices=column_indices)
                if 'subject' in spec.keys():
                    subject_data['subject'] = subject
                if 'side' in spec.keys():
                    subject_data['side'] = side
                if 'collection' in spec.keys():
                    subject_data['collection'] = datapoint.query.collection_id
                store.append(subject_data)


    def __len__(self):
        return len(self._features)


    def __getitem__(self, idx):
        def get_single_item(features, target, group):
            # unify both to simpify on-demand transforms
            characteristics = {**features, **target, **group}

            if 'images' in characteristics:
                width, height = characteristics['images'].size
                resized_im = characteristics['images'].resize((32, 32), resample=LANCZOS, box=(width//2-128, height//2-128, width//2+128, height//2+128)).convert('L')
                if self._image_transform:
                    resized_im = self._image_transform(resized_im)
                # resized_im = resized_im.transpose((1, 2, 0))  # convert to HWC
                characteristics['images'] = resized_im
            if 'anthropometry' in characteristics and self._measurement_transform:
                characteristics['anthropometry'] = self._measurement_transform(characteristics['anthropometry'])
            if 'hrirs' in characteristics and self._hrir_transform:
                characteristics['hrirs'] = self._hrir_transform(characteristics['hrirs'])

            def shape_data(keys):
                if len(keys) == 0:
                    return np.array([])
                if len(keys) == 1:
                    return characteristics[list(keys)[0]]
                return tuple(characteristics[k] for k in keys)

            return {
                'features': shape_data(features.keys()),
                'target': shape_data(target.keys()),
                'group': shape_data(group.keys()),
            }

        if isinstance(idx, int):
            return get_single_item(self._features[idx], self._targets[idx], self._groups[idx])
        else:
            items = []
            for features, target, group in zip(self._features[idx], self._targets[idx], self._groups[idx]):
                items.append(get_single_item(features, target, group))
            try:
                return {k: np.stack([d[k] for d in items]) for k in items[0].keys()}
            except ValueError as exc:
                raise ValueError('Not all data points have the same shape') from exc


    @property
    def target_shape(self):
        return np.hstack(tuple(self._targets[0].values())).shape


    @property
    def available_subject_ids(self):
        ear_ids = self._query.specification_based_ids(self._specification, exclude_subjects=self._exclude_ids)
        subject_ids, _ = zip(*ear_ids)
        return tuple(sorted(set(subject_ids)))


class CIPIC(HRTFDataset):
    """CIPIC HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        measurement_transform: Optional[Callable] = None,
        hrir_transform: Optional[Callable] = None,
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = CipicDataPoint(
            anthropomorphy_matfile_path=Path(root)/'CIPIC_hrtf_database/anthropometry/anthro.mat',
            sofa_directory_path=Path(root)/'sofa',
            hrir_samplerate=hrir_samplerate,
            hrir_length=hrir_length,
            dtype=dtype,
        )
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, measurement_transform, hrir_transform)


class ARI(HRTFDataset):
    """ARI HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        measurement_transform: Optional[Callable] = None,
        hrir_transform: Optional[Callable] = None,
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = AriDataPoint(
            anthropomorphy_matfile_path=Path(root)/'anthro.mat',
            sofa_directory_path=Path(root)/'sofa',
            hrir_samplerate=hrir_samplerate,
            hrir_length=hrir_length,
            dtype=dtype,
        )
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, measurement_transform, hrir_transform)


class Listen(HRTFDataset):
    """Listen HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrir_transform: Optional[Callable] = None,
        hrtf_type: str = 'compensated',
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = ListenDataPoint(sofa_directory_path=Path(root)/'sofa', hrtf_type=hrtf_type, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, dtype=dtype)
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, None, hrir_transform)


class BiLi(HRTFDataset):
    """BiLi HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrir_transform: Optional[Callable] = None,
        hrtf_type: str = 'compensated',
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = BiLiDataPoint(sofa_directory_path=Path(root)/'sofa', hrtf_type=hrtf_type, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, dtype=dtype)
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, None, hrir_transform)


class ITA(HRTFDataset):
    """ITA HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrir_transform: Optional[Callable] = None,
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = ItaDataPoint(sofa_directory_path=Path(root)/'sofa', hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, dtype=dtype)
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, None, hrir_transform)


class HUTUBS(HRTFDataset):
    """HUTUBS HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrir_transform: Optional[Callable] = None,
        measured_hrtf: bool = True,
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = HutubsDataPoint(sofa_directory_path=Path(root)/'sofa', measured_hrtf=measured_hrtf, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, dtype=dtype)
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, None, hrir_transform)


class RIEC(HRTFDataset):
    """RIEC HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrir_transform: Optional[Callable] = None,
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = RiecDataPoint(sofa_directory_path=Path(root)/'sofa', hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, dtype=dtype)
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, None, hrir_transform)


class CHEDAR(HRTFDataset):
    """CHEDAR HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrir_transform: Optional[Callable] = None,
        radius: float = 1,
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = ChedarDataPoint(sofa_directory_path=Path(root)/'sofa', radius=radius, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, dtype=dtype)
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, None, hrir_transform)


class Widespread(HRTFDataset):
    """Widespread HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrir_transform: Optional[Callable] = None,
        radius: float = 1,
        grid: str = 'UV',
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = WidespreadDataPoint(sofa_directory_path=Path(root)/'sofa', radius=radius, grid=grid, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, dtype=dtype)
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, None, hrir_transform)


class SADIE2(HRTFDataset):
    """SADIE II HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrir_transform: Optional[Callable] = None,
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = Sadie2DataPoint(sofa_directory_path=Path(root)/'Database-Master_V1-4', hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, dtype=dtype)
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, None, hrir_transform)


class ThreeDThreeA(HRTFDataset):
    """3D3A HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrir_transform: Optional[Callable] = None,
        hrtf_method: str = 'measured',
        hrtf_type: str = 'compensated',
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = ThreeDThreeADataPoint(sofa_directory_path=Path(root)/'HRTFs', hrtf_method=hrtf_method, hrtf_type=hrtf_type, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, dtype=dtype)
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, None, hrir_transform)


class SONICOM(HRTFDataset):
    """SONICOM HRTF Dataset
    """
    def __init__(
        self,
        root: str,
        feature_spec: Dict,
        target_spec: Optional[Dict] = None,
        group_spec: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        subject_requirements: Optional[Dict] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrir_transform: Optional[Callable] = None,
        hrtf_type: str = 'compensated',
        dtype: type = np.float32,
        # download: bool = True,
    ) -> None:
        hrir_samplerate, hrir_length = _get_samplerate_and_length_from_spec(feature_spec, target_spec, group_spec)
        datapoint = SonicomDataPoint(sofa_directory_path=Path(root), hrtf_type=hrtf_type, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, dtype=dtype)
        super().__init__(datapoint, feature_spec, target_spec, group_spec, subject_ids, subject_requirements, exclude_ids, None, None, hrir_transform)