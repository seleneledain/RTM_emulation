'''
Extract Sentinel-2 surface reflectance (SRF) data for selected field parcels
over the growing season and run PROSAIL simulations.

@author Lukas Valentin Graf, Selene Ledain
'''

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import pickle
import tempfile
import urllib
import uuid
from datetime import datetime
import planetary_computer

import os
from pathlib import Path
import sys
base_dir = Path(os.path.dirname(os.path.realpath("__file__"))).parent
sys.path.insert(0, os.path.join(base_dir, "eodal"))
from eodal.config import get_settings
from eodal.core.scene import SceneCollection
from eodal.core.sensors.sentinel2 import Sentinel2
from eodal.mapper.feature import Feature
from eodal.mapper.filter import Filter
from eodal.mapper.mapper import Mapper, MapperConfigs
from eodal.metadata.sentinel2.parsing import parse_MTD_TL
from eodal.utils.sentinel2 import get_S2_platform_from_safe, _url_to_safe_name
from pathlib import Path
from rtm_inv.core.lookup_table import generate_lut
from typing import Any, Dict, List, Optional

from utils import get_farms

settings = get_settings()
settings.USE_STAC = True # False # 
logger = settings.logger

# Sentinel-2 bands to extract and use for PROSAIL runs
band_selection = [
    'B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B8A', 'B11', 'B12']


def angles_from_mspc(url: str) -> Dict[str, float]:
    """
    Extract viewing and illumination angles from MS Planetary Computer
    metadata XML (this is a work-around until STAC provides the angles
    directly)

    :param url:
        URL to the metadata XML file
    :returns:
        extracted angles as dictionary
    """
    response = urllib.request.urlopen(planetary_computer.sign_url(url)).read()
    temp_file = os.path.join(tempfile.gettempdir(), f'{uuid.uuid4()}.xml')
    with open(temp_file, 'wb') as dst:
        dst.write(response)

    metadata = parse_MTD_TL(in_file=temp_file)
    # get sensor zenith and azimuth angle
    sensor_angles = ['SENSOR_ZENITH_ANGLE', 'SENSOR_AZIMUTH_ANGLE']
    sensor_angle_dict = {
        k: v for k, v in metadata.items() if k in sensor_angles}
    return sensor_angle_dict


def preprocess_sentinel2_scenes(
        ds: Sentinel2,
        target_resolution: int,
    ) -> Sentinel2:
    """
    Resample Sentinel-2 scenes and mask clouds, shadows, and snow
    based on the Scene Classification Layer (SCL).

    NOTE:
        Depending on your needs, the pre-processing function can be
        fully customized using the full power of EOdal and its
        interfacing libraries!

    :param target_resolution:
        spatial target resolution to resample all bands to.
    :returns:
        resampled, cloud-masked Sentinel-2 scene.
    """
    # resample scene
    ds.resample(inplace=True, target_resolution=target_resolution)
    # mask clouds, shadows, and snow
    ds.mask_clouds_and_shadows(inplace=True)
    return ds


def get_s2_mapper(
    s2_mapper_config: MapperConfigs,
    output_dir: Path
    ) -> Mapper:
    """
    Setup an EOdal `Mapper` instance, query and load Sentinel-2 data

    :param s2_mapper_config:
        configuration telling EOdal what to do (which geographic region and
        time period should be processed)
    :param output_dir:
        directory where to store the query for documentation
    :returns:
        EOdal `Mapper` instance with populated `metadata` and `data`
        attributes
    """
    # setup Sentinel-2 mapper to get the relevant scenes
    mapper = Mapper(s2_mapper_config)
    # check if the metadata and data has been already saved.
    # In this case we can simply read the data from file and create
    # a new mapper instance
    fpath_metadata = output_dir.joinpath('eodal_mapper_metadata.gpkg')
    fpath_mapper = output_dir.joinpath('eodal_mapper_scenes.pkl')
    if fpath_mapper.exists() and fpath_metadata.exists():
        metadata = gpd.read_file(fpath_metadata)
        scenes = SceneCollection.from_pickle(stream=fpath_mapper)
        mapper.data = scenes
        mapper.metadata = metadata
        return mapper
    # otherwise, it's necessary to query the data again
    # query metadata records
    mapper.query_scenes()
    
    # extract the angular information about the sensor (still not
    # part of the default STAC metadata). Since it's only a work-
    # around it's a bit slow...
    mapper.metadata['href_xml'] = mapper.metadata.assets.apply(
        lambda x: x['granule-metadata']['href']
    )
    mapper.metadata['sensor_angles'] = mapper.metadata['href_xml'].apply(
        lambda x, angles_from_mspc=angles_from_mspc: angles_from_mspc(x)
    )
    mapper.metadata['sensor_zenith_angle'] = \
        mapper.metadata['sensor_angles'].apply(
            lambda x: x['SENSOR_ZENITH_ANGLE'])

    mapper.metadata['sensor_azimuth_angle'] = \
        mapper.metadata['sensor_angles'].apply(
            lambda x: x['SENSOR_AZIMUTH_ANGLE'])

    # load the Sentinel-2 scenes and resample them to 10 m, apply cloud masking
    scene_kwargs = {
        'scene_constructor': Sentinel2.from_safe,
        'scene_constructor_kwargs': {'band_selection': band_selection},
        'scene_modifier': preprocess_sentinel2_scenes,
        'scene_modifier_kwargs': {'target_resolution': 10}
    }
    mapper.load_scenes(scene_kwargs=scene_kwargs)
    # loop over scenes and remove those that were completely cloudy
    mapper.metadata['scene_used'] = 'yes'
    scenes_to_del = []
    for scene_id, scene in mapper.data:
        # check if scene is blackfilled (nodata); if yes continue
        if scene.is_blackfilled:
            scenes_to_del.append(scene_id)
            mapper.metadata.loc[
                mapper.metadata.sensing_time.dt.strftime('%Y-%m-%d %H:%M') ==
                scene_id.strftime(
                    '%Y-%m-%d %H:%M')[0:16], 'scene_used'] = 'No [blackfill]'
            continue
        if scene['blue'].values.mask.all():
            scenes_to_del.append(scene_id)
            mapper.metadata.loc[
                mapper.metadata.sensing_time.dt.strftime('%Y-%m-%d %H:%M') ==
                scene_id.strftime(
                    '%Y-%m-%d %H:%M')[0:16], 'scene_used'] = 'No [clouds]'
            continue
    # delete scenes too cloudy or containing only no-data
    for scene_id in scenes_to_del:
        del mapper.data[scene_id]
    # save the MapperConfigs as yaml file
    s2_mapper_config.to_yaml(
        fpath=output_dir.joinpath('eodal_mapper_configs.yml'))
    # save the mapper data as pickled object so it can be loaded again
    with open(fpath_mapper, 'wb+') as dst:
        dst.write(mapper.data.to_pickle())
    # save the mapper metadata as GeoPackage
    mapper.metadata.sensing_date = mapper.metadata.sensing_date.astype(str)
    if 'real_path' in mapper.metadata.columns:
        mapper.metadata.real_path = mapper.metadata.real_path.astype(str)
    if '_processing_level' in mapper.metadata.columns:
        mapper.metadata._processing_level = \
            mapper.metadata._processing_level.astype(str)
    # drop the original XMLs as they are too large
    if 'mtd_tl_xml' in mapper.metadata.columns:
        mapper.metadata.drop(columns=['mtd_tl_xml'], inplace=True)
    if 'mtd_msi_xml' in mapper.metadata.columns:
        mapper.metadata.drop(columns=['mtd_msi_xml'], inplace=True)
    mapper.metadata.to_file(fpath_metadata)

    return mapper


def get_s2_spectra(
    output_dir: Path,
    lut_params_dir: Path,
    s2_mapper_config: Dict[str, Any],
    rtm_lut_config: Dict[str, Any],
    traits: List[str],
    apply_contraints: Optional[bool] = True
    ) -> None:
    """
    Extract S2 SRF for field parcel geometries and run PROSAIL in forward mode

    :param output_dir:
        directory where to save extracted S2 data and PROSAIL outputs to
    :param lut_params_dir:
        directory where the PROSAIL inputs are stored
    :param s2_mapper_config:
        configuration telling EOdal what to do (which geographic region and
        time period should be processed)
    :param rtm_lut_config:
        configuration telling how to build the lookup tables (LUTs) required
        to run PROSAIL
    :param traits:
        name of the PROSAIL traits to save to the LUTs (determines which traits
        are available from the inversion)
    :param apply_constraints:
        whether to apply the GLAI-CCC and Cab-Car constraint. Default is True.
    """
    trait_str = '-'.join(traits)
    mapper = get_s2_mapper(s2_mapper_config, output_dir=output_dir)
    s2_data = mapper.data
    s2_metadata = mapper.metadata
    s2_metadata['sensing_date'] = pd.to_datetime(s2_metadata.sensing_date)
    # loop over mapper
    for _, scene in s2_data:
        # make sure we're looking at the right metadata
        metadata = s2_metadata[
            s2_metadata.sensing_date.dt.date ==
            scene.scene_properties.acquisition_time.date()
        ]
        # to speed model development we use only all_pheno
        pheno_phase_selection = ['all_phases']
        
        # get viewing and illumination angles for PROSAIL run
        angle_dict = {
            'solar_zenith_angle': metadata['sun_zenith_angle'].iloc[0],
            'solar_azimuth_angle': metadata['sun_azimuth_angle'].iloc[0],
            'viewing_zenith_angle': metadata['sensor_zenith_angle'].iloc[0],
            'viewing_azimuth_angle': metadata['sensor_azimuth_angle'].iloc[0]
        }
        
        # get platform
        platform =metadata['product_uri'].iloc[0].split('_')[0]
        #get_S2_platform_from_safe(dot_safe_name=metadata['product_uri'].iloc[0])

        # map to full platform name
        full_names = {'S2A': 'Sentinel2A', 'S2B': 'Sentinel2B'}
        platform = full_names[platform]
        rtm_lut_config.update({'sensor': platform})

        # save spectra and PROSAIL simulations in a sub-directory for
        # each scene
        res_dir_scene = output_dir.joinpath(metadata['product_uri'].iloc[0])
        if not str(res_dir_scene).endswith('.SAFE'):
            res_dir_scene = Path(str(res_dir_scene) + '.SAFE')
        res_dir_scene.mkdir(exist_ok=True)

        # save S2 spectra to disk for analysis
        scene.to_rasterio(res_dir_scene.joinpath('SRF_S2.tiff'))
        fig_s2_rgb = scene.plot_multiple_bands(['blue', 'green', 'red'])
        fname_fig_s2_rgb = res_dir_scene.joinpath('SRF_S2_VIS.png')
        fig_s2_rgb.savefig(fname_fig_s2_rgb)
        plt.close(fig_s2_rgb)

        # run PROSAIL forward runs for the different parametrizations available
        logger.info(f'{metadata.product_uri.iloc[0]} starting PROSAIL runs')
        lut_params_pheno = lut_params_dir.joinpath('prosail_danner-etal_all_phases.csv') # Only use general params for LUT
    
        pheno_phases = \
            lut_params_pheno.name.split('etal')[-1].split('.')[0][1::]
        if pheno_phase_selection is not None:
            if pheno_phases not in pheno_phase_selection:
                continue

        # generate lookup-table for the current angles
        if apply_contraints:
            fpath_lut = res_dir_scene.joinpath(
                f'{pheno_phases}_{trait_str}_lut.pkl')
        else:
            fpath_lut = res_dir_scene.joinpath(
                f'{pheno_phases}_{trait_str}_lut_no-constraints.pkl')
        # if LUT exists, continue, else generate it
        if not fpath_lut.exists():
            lut_inp = rtm_lut_config.copy()
            lut_inp.update(angle_dict)
            if not apply_contraints:
                lut_inp.update({
                    'apply_glai_ccc_constraint': False,
                    'apply_chlorophyll_carotiniod_constraint': False
                })
            lut_inp['lut_params'] = lut_params_pheno
            lut = generate_lut(**lut_inp)
            # special case CCC (Canopy Chlorophyll Content) ->
            # this is not a direct RTM output
            if 'ccc' in traits:
                lut['ccc'] = lut['lai'] * lut['cab']
                # convert to g m-2 as this is the more common unit
                # ug -> g: factor 1e-6; cm2 -> m2: factor 1e-4
                lut['ccc'] *= 1e-2

            # prepare LUT for model training
            # lut = lut[band_selection + traits].copy()
            lut.dropna(inplace=True)

            # save LUT to file
            # if not fpath_lut.exists():
            with open(fpath_lut, 'wb+') as f:
                pickle.dump(lut, f)
        else:
            continue

        logger.info(f'{metadata.product_uri.iloc[0]} finished PROSAIL runs')


if __name__ == '__main__':

    cwd = Path(__file__).parent.absolute()
    import os
    os.chdir(cwd)

    # global setup
    out_dir = Path('../results').joinpath('lut_based_inversion')
    out_dir.mkdir(exist_ok=True)

    # spectral response function of Sentinel-2 for resampling PROSAIL output
    fpath_srf = Path(
        '../data/auxiliary/S2-SRF_COPE-GSEG-EOPG-TN-15-0007_3.1.xlsx')
    # RTM configurations for lookup-table generation
    rtm_lut_config = {
        'lut_size': 50000,
        'fpath_srf': fpath_srf,
        'remove_invalid_green_peaks': True,
        'sampling_method': 'FRS',
        'linearize_lai': False
    }
    # directory with LUT parameters for different phenological macro-stages
    lut_params_dir = Path('lut_params')

    # target trait(s)
    traits = ['lai', 'cab', 'ccc', 'car']

    # metadata filters for retrieving S2 scenes
    metadata_filters = [
        Filter('cloudy_pixel_percentage', '<', 50),
        Filter('processing_level', '==', 'Level-2A')
    ]

    #######################################################################

    # extraction for 2019
    data_dir = Path('../data/auxiliary/')
    year = 2019
    farms = ['eschikon']

    # get field parcel geometries organized by farm
    farm_gdf_dict = get_farms(data_dir, farms, year)

    # loop over farms
    for farm, geom in farm_gdf_dict.items():
        logger.info(f'Working on {farm}')
        # S2 configuration (for data extraction and pre-processing)
        feature = Feature.from_geoseries(gds=geom.geometry)
        s2_mapper_config = MapperConfigs(
            collection='sentinel2-msi',
            time_start=datetime(year, 1, 1),
            time_end=datetime(year, 12,31),
            feature=feature,
            metadata_filters=metadata_filters
        )

        output_dir_farm = out_dir.joinpath(f'{farm}')
        output_dir_farm.mkdir(exist_ok=True)

        try:
            get_s2_spectra(
                output_dir=output_dir_farm,
                lut_params_dir=lut_params_dir,
                s2_mapper_config=s2_mapper_config,
                rtm_lut_config=rtm_lut_config,
                traits=traits
            )
        except Exception as e:
            logger.error(f'Farm {farm}: {e}')
            continue

        logger.info(f'Finished working on {farm}')