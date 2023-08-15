from typing import Dict, Iterable, Optional, Union
from numbers import Number
import numpy as np
from .full import Cipic, Ari, Listen, BiLi, Ita, Hutubs, Riec, Chedar, Widespread, Sadie2, Princeton3D3A, Sonicom
from .display import plot_hrir_plane, plot_hrtf_plane, plot_plane_angles, plot_hrir_lines, plot_hrtf_lines
from .transforms.hrirs import PlaneTransform, InterauralPlaneTransform, SphericalPlaneTransform
from .util import lateral_vertical_from_yaw, lateral_vertical_from_pitch, lateral_vertical_from_roll, azimuth_elevation_from_yaw, azimuth_elevation_from_pitch, azimuth_elevation_from_roll


class PlaneMixin:
    def __init__(self,
        plane: str,
        domain: str,
        side: str,
        distance: Union[float, str],
        plane_offset: float,
        fundamental_angles: Iterable[float],
        orthogonal_angles: Iterable[float],
        planar_transform: PlaneTransform,
        hrir_offset: Optional[float],
        hrir_scaling: Optional[float],
        hrir_samplerate: Optional[float],
        hrir_length: Optional[float],
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        **kwargs,
    ):
        if plane not in ('horizontal', 'median', 'frontal', 'vertical', 'interaural'):
            raise ValueError('Unknown plane "{}", needs to be "horizontal", "median", "frontal", "vertical" or "interaural".')
        self._plane = plane
        self._plane_offset = plane_offset
        self._domain = domain
        self._planar_transform = planar_transform
        hrirs_spec = {'hrirs': {'fundamental_angles': fundamental_angles, 'orthogonal_angles': orthogonal_angles, 'side': side, 'domain': domain, 'distance': distance, 'additive_scale_factor': hrir_offset, 'multiplicative_scale_factor': hrir_scaling, 'samplerate': hrir_samplerate, 'length': hrir_length, 'min_phase': hrir_min_phase, 'transform': planar_transform}}
        if other_specs is None:
            other_specs = {}
        for spec_name in other_specs.keys():
            if hrir_role == spec_name.split('_spec')[0]:
                raise ValueError(f'No {spec_name} should be given since that role is already taken by the HRIRs')
        specs = {hrir_role+'_spec': hrirs_spec, **other_specs}
        super().__init__(**specs, **kwargs)
        self.plane_angles = planar_transform.calc_plane_angles(self.fundamental_angles, self.orthogonal_angles, self._selection_mask)


    @property
    def positive_angles(self):
        return self._planar_transform.positive_angles


    @positive_angles.setter
    def positive_angles(self, value):
        self._planar_transform.positive_angles = value
        self.plane_angles = self._planar_transform.calc_plane_angles(self.fundamental_angles, self.orthogonal_angles, self._selection_mask)


    @property
    def min_angle(self):
        return self._planar_transform.min_angle


    @property
    def max_angle(self):
        return self._planar_transform.max_angle


    @property
    def plane_angle_name(self):
        if self._plane in ('horizontal', 'interaural'):
            return 'yaw [°]'
        elif self._plane in ('median', 'vertical'):
            return 'pitch [°]'
        else: # frontal plane
            return 'roll [°]'


    def plot_plane(self, idx, ax=None, vmin=None, vmax=None, title=None, lineplot=False, cmap='viridis', continuous=False, colorbar=True, log_freq=False):
        hrir_role = 'features' if 'hrirs' in self._features_keys else 'target' if 'hrirs' in self._target_keys else 'group'
        if vmin is None or vmax is None:
            all_hrirs = self[:][hrir_role]
            if vmin is None:
                vmin = all_hrirs.min()
            if vmax is None:
                vmax = all_hrirs.max()
        data = self[idx][hrir_role]

        if self._domain == 'time':
            if lineplot:
                ax = plot_hrir_lines(data, self.plane_angles, self.plane_angle_name, self.hrir_samplerate, ax=ax, vmin=vmin, vmax=vmax)
            else:
                ax = plot_hrir_plane(data, self.plane_angles, self.plane_angle_name, self.hrir_samplerate, ax=ax, vmin=vmin, vmax=vmax, cmap=cmap, continuous=continuous, colorbar=colorbar)
        else:
            if lineplot:
                ax = plot_hrtf_lines(data, self.plane_angles, self.plane_angle_name, self.hrtf_frequencies, log_freq=log_freq, ax=ax, vmin=vmin, vmax=vmax)
            else:
                ax = plot_hrtf_plane(data, self.plane_angles, self.plane_angle_name, self.hrtf_frequencies, log_freq=log_freq, ax=ax, vmin=vmin, vmax=vmax, cmap=cmap, continuous=continuous, colorbar=colorbar)

        if title is None:
            title = "{} Plane{} of Subject {}'s {} Ear".format(self._plane.title(),
                ' With Offset {}°'.format(self._plane_offset) if self._plane_offset != 0 or self._plane in ('vertical', 'interaural') else '',
                self.subject_ids[idx],
                self.sides[idx].replace('-', ' ').title(),
            )
        ax.set_title(title)
        return ax


    def plot_angles(self, ax=None, title=None):
        if self._plane in ('horizontal', 'interaural', 'frontal'):
            zero_location = 'N'
            direction = 'counterclockwise'
        else: # median or vertical
            zero_location = 'W'
            direction = 'clockwise'
        ax = plot_plane_angles(self.plane_angles, self.min_angle, self.max_angle, True, 1, zero_location, direction, ax) # TODO use actual radius
        if title is None:
            title = 'Angles in the {} Plane{}'.format(self._plane.title(),
                ' With Offset {}°'.format(self._plane_offset) if self._plane_offset != 0 or self._plane in ('vertical', 'interaural') else ''
            )
        ax.set_title(title)
        return ax


class InterauralPlaneMixin(PlaneMixin):
    def __init__(self,
        plane: str,
        domain: str,
        side: str,
        plane_angles: Optional[Iterable[float]],
        plane_offset: float,
        positive_angles: bool,
        distance: Union[float, str],
        **kwargs,
    ):
        if plane == 'horizontal':
            if plane_offset != 0:
                raise ValueError('Only the horizontal plane at vertical angle 0 is available in an interaural coordinate dataset')
            lateral_angles, vertical_angles = InterauralPlaneMixin._lateral_vertical_from_yaw(plane_angles, plane_offset)
        elif plane == 'median':
            lateral_angles, vertical_angles = InterauralPlaneMixin._lateral_vertical_from_pitch(plane_angles, plane_offset)
        elif plane == 'frontal':
            if plane_offset != 0:
                raise ValueError('Only the frontal plane at vertical angles +/-90 is available in an interaural coordinate dataset')
            lateral_angles, vertical_angles = InterauralPlaneMixin._lateral_vertical_from_roll(plane_angles, plane_offset)
        elif plane == 'interaural':
            lateral_angles, vertical_angles = InterauralPlaneMixin._lateral_vertical_from_yaw(plane_angles, plane_offset)
        else:
            if plane not in ('horizontal', 'median', 'frontal', 'interaural'):
                raise ValueError('Unknown plane "{}", needs to be "horizontal", "median", "frontal" or "interaural".')

        plane_transform = InterauralPlaneTransform(plane, plane_offset, positive_angles)
        super().__init__(plane, domain, side, distance, plane_offset, vertical_angles, lateral_angles, plane_transform, **kwargs)


    @staticmethod
    def _lateral_vertical_from_yaw(yaw_angles, plane_offset=0):
        if yaw_angles is None:
            return None, (plane_offset - 180, plane_offset)
        return lateral_vertical_from_yaw(yaw_angles, plane_offset)


    @staticmethod
    def _lateral_vertical_from_pitch(pitch_angles, plane_offset=0):
        if pitch_angles is None:
            return (plane_offset,), None
        return lateral_vertical_from_pitch(pitch_angles, plane_offset)


    @staticmethod
    def _lateral_vertical_from_roll(roll_angles, plane_offset=0):
        if roll_angles is None:
            return None, (plane_offset - 90, plane_offset + 90)
        return lateral_vertical_from_roll(roll_angles, plane_offset)


class SphericalPlaneMixin(PlaneMixin):
    def __init__(self,
        plane: str,
        domain: str,
        side: str,
        plane_angles: Optional[Iterable[float]],
        plane_offset: float,
        positive_angles: bool,
        distance: Union[float, str],
        **kwargs,
    ):
        if plane == 'horizontal':
            azimuth_angles, elevation_angles = SphericalPlaneMixin._azimuth_elevation_from_yaw(plane_angles, plane_offset)
        elif plane == 'median':
            if plane_offset != 0:
                raise ValueError('Only the median plane at azimuth 0 is available in a spherical coordinate dataset')
            azimuth_angles, elevation_angles = SphericalPlaneMixin._azimuth_elevation_from_pitch(plane_angles, plane_offset)
        elif plane == 'frontal':
            if plane_offset != 0:
                raise ValueError('Only the frontal plane at azimuth +/-90 is available in a spherical coordinate dataset')
            azimuth_angles, elevation_angles = SphericalPlaneMixin._azimuth_elevation_from_roll(plane_angles, plane_offset)
        elif plane == 'vertical':
            azimuth_angles, elevation_angles = SphericalPlaneMixin._azimuth_elevation_from_pitch(plane_angles, plane_offset)
        else:
            raise ValueError('Unknown plane "{}", needs to be "horizontal", "median", "frontal" or "vertical".')

        plane_transform = SphericalPlaneTransform(plane, plane_offset, positive_angles)
        super().__init__(plane, domain, side, distance, plane_offset, azimuth_angles, elevation_angles, plane_transform, **kwargs)


    @staticmethod
    def _azimuth_elevation_from_yaw(yaw_angles, plane_offset=0):
        if yaw_angles is None:
            return None, (plane_offset,)
        return azimuth_elevation_from_yaw(yaw_angles, plane_offset)


    @staticmethod
    def _azimuth_elevation_from_pitch(pitch_angles, plane_offset=0):
        if pitch_angles is None:
            return (plane_offset - 180, plane_offset), None
        return azimuth_elevation_from_pitch(pitch_angles, plane_offset)


    @staticmethod
    def _azimuth_elevation_from_roll(roll_angles, plane_offset=0):
        if roll_angles is None:
            return (plane_offset - 90, plane_offset + 90), None
        return azimuth_elevation_from_roll(roll_angles, plane_offset)


class CipicPlane(InterauralPlaneMixin, Cipic):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = True,
    ):
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, 'farthest', root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, dtype=dtype,
            download=download, verify=verify,
        )


class AriPlane(SphericalPlaneMixin, Ari):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = True,
    ):
        if positive_angles is None:
            positive_angles = False
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, 'farthest', root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, dtype=dtype,
            download=download, verify=verify,
        )


class ListenPlane(SphericalPlaneMixin, Listen):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrtf_type: str = 'compensated',
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = True,
    ):
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, 'farthest', root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, hrtf_type=hrtf_type, dtype=dtype,
            download=download, verify=verify,
        )


class BiLiPlane(SphericalPlaneMixin, BiLi):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrtf_type: str = 'compensated',
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = True,
    ):
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, 'farthest', root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, dtype=dtype, hrtf_type=hrtf_type,
            download=download, verify=verify,
        )


class ItaPlane(SphericalPlaneMixin, Ita):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = True,
    ):
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, 'farthest', root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, dtype=dtype,
            download=download, verify=verify,
        )


class HutubsPlane(SphericalPlaneMixin, Hutubs):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        measured_hrtf: bool = True,
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = True,
    ):
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, 'farthest', root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, dtype=dtype, measured_hrtf=measured_hrtf,
            download=download, verify=verify,
        )


class RiecPlane(SphericalPlaneMixin, Riec):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        distance: Union[float, str] = 'farthest',
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = True,
    ):
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, distance, root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, dtype=dtype,
            download=download, verify=verify,
        )


class ChedarPlane(SphericalPlaneMixin, Chedar):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        distance: Union[float, str] = 'farthest',
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = False,
    ):
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, distance, root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, dtype=dtype,
            download=download, verify=verify,
        )


class WidespreadPlane(SphericalPlaneMixin, Widespread):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        distance: Union[float, str] = 'farthest',
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        grid: str = 'UV',
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = False,
    ):
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, distance, root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, dtype=dtype, grid=grid,
            download=download, verify=verify,
        )


class Sadie2Plane(SphericalPlaneMixin, Sadie2):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = True,
    ):
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, 'farthest', root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, dtype=dtype,
            download=download, verify=verify,
        )


class Princeton3D3APlane(SphericalPlaneMixin, Princeton3D3A):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrtf_method: str = 'measured',
        hrtf_type: str = 'compensated',
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = True,
    ):
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, 'farthest', root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, dtype=dtype, hrtf_method=hrtf_method, hrtf_type=hrtf_type,
            download=download, verify=verify,
        )


class SonicomPlane(SphericalPlaneMixin, Sonicom):
    def __init__(self,
        root: str,
        plane: str,
        domain: str = 'magnitude_db',
        side: str = 'left',
        plane_angles: Optional[Iterable[float]] = None,
        plane_offset: float = 0.,
        positive_angles: bool = False,
        hrir_offset: Optional[float] = None,
        hrir_scaling: Optional[float] = None,
        hrir_samplerate: Optional[float] = None,
        hrir_length: Optional[float] = None,
        hrir_min_phase: bool = False,
        hrir_role: str = 'features',
        other_specs: Optional[Dict] = None,
        subject_ids: Optional[Iterable[int]] = None,
        exclude_ids: Optional[Iterable[int]] = None,
        hrtf_type: str = 'compensated',
        dtype: type = np.float32,
        download: bool = False,
        verify: bool = True,
    ):
        super().__init__(
            plane, domain, side, plane_angles, plane_offset, positive_angles, 'farthest', root=root,
            hrir_offset=hrir_offset, hrir_scaling=hrir_scaling, hrir_samplerate=hrir_samplerate, hrir_length=hrir_length, hrir_min_phase=hrir_min_phase,
            hrir_role=hrir_role, other_specs=other_specs, subject_ids=subject_ids, exclude_ids=exclude_ids, dtype=dtype, hrtf_type=hrtf_type,
            download=download, verify=verify,
        )
