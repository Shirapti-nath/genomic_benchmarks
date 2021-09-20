import pandas as pd
import yaml
import gzip
import re
import urllib
import shutil  # for removing and creating folders
from pathlib import Path
from tqdm.auto import tqdm

from Bio import SeqIO


CACHE_PATH = Path.home() / '.genomic_benchmarks'
REF_CACHE_PATH = CACHE_PATH / 'fasta'


def create_seq_genomic_dataset(interval_list_dataset, dest_path=CACHE_PATH, cache_path=REF_CACHE_PATH, force_download=False):
    '''
    From an interval-list genomic dataset creates full-seq genomic dataset.

            Parameters:
                    interval_list_dataset (str or Path): Either a path or a name of dataset included in this package.
                    dest_path (str or Path): Folder to store the full-seq dataset.
                    cache_path (str or Path): Folder to store the downloaded references.
                    force_download (bool): If True, force downloading of references.

            Returns:
                    seq_dataset_path (Path): Path to the full-seq dataset.
    '''
    # TODO: implement interval_list_dataset to be a name, not path

    metadata = _check_dataset_existence(interval_list_dataset)
    dataset_name = _get_dataset_name(interval_list_dataset)
    refs = _download_references(metadata, cache_path=cache_path, force=force_download)
    fastas = _load_fastas_into_memory(refs, cache_path=cache_path)

    _remove_and_create(Path(dest_path) / dataset_name)
    _remove_and_create(Path(dest_path) / dataset_name / "train")
    _remove_and_create(Path(dest_path) / dataset_name / "test")

    for c in metadata['classes']:
        for t in ['train', 'test']:
            dt_filename = Path(interval_list_dataset) / t / (c + '.csv')
            dt = pd.read_csv(dt_filename)

            ref_name = _get_reference_name(metadata['classes'][c]['url'])
            dt['seq'] = _fill_seq_column(fastas[ref_name], dt)

            folder_filename = Path(dest_path) / dataset_name / t / c
            _remove_and_create(folder_filename)
            for row in dt.iterrows():
                row_filename = folder_filename / (str(row[1]['id']) + '.txt')
                row_filename.write_text(row[1]['seq'])
    
    return Path(dest_path) / dataset_name


def _check_dataset_existence(interval_list_dataset):
    # check that the dataset exists, returns its metadata
    path = Path(interval_list_dataset)
    if not path.exists():
        raise FileNotFoundError(f'Dataset {interval_list_dataset} not found.')

    metadata_path = path / 'metadata.yaml'
    if not metadata_path.exists():
        raise FileNotFoundError(f'Dataset {interval_list_dataset} does not contain `metadata.yaml` file.')
    with open(metadata_path, "r") as fr:
        metadata = yaml.safe_load(fr)
    return metadata

def _get_dataset_name(path):
    # get the dataset name from the path
    path = str(path)
    return path.split('/')[-1]

def _download_references(metadata, cache_path, force=False):
    # download all references from the metadata into cache_path folder
    cache_path = Path(cache_path)
    if not cache_path.exists():
        cache_path.mkdir(parents=True)

    refs = {(c['url'], c['type'], c.get('extra_processing')) for c in metadata['classes'].values()}

    for ref in refs:
        ref_path = cache_path / _get_reference_name(ref[0])
        if not ref_path.exists() or force:
            _download_url(ref[0], ref_path)
        else:
            print(f'Reference {ref_path} already exists. Skipping.')
        
    return refs

def _get_reference_name(url):
    # get the reference name from the url
    ### TODO: better naming scheme (e.g. taking the same file from 2 Ensembl releases)
    return url.split('/')[-1]

def _download_url(url, dest):
    # download a file from url to dest
    if Path(dest).exists():
        Path(dest).unlink()

    print(f"Downloading {url}") 
    class DownloadProgressBar(tqdm):
        # for progress bar
        def update_to(self, b=1, bsize=1, tsize=None):
            if tsize is not None:
                self.total = tsize
            self.update(b * bsize - self.n)

    with DownloadProgressBar(unit='B', unit_scale=True,
                             miniters=1, desc=str(dest)) as t:
        # TODO: adapt fastdownload code instead of urllib
        urllib.request.urlretrieve(url, filename=dest, reporthook=t.update_to)

EXTRA_PREPROCESSING = {
    'default': [None, None, lambda x: x],
    'ENSEMBL_HUMAN_GENOME': [24, 'MT', lambda x: "chr"+x],
    'ENSEMBL_MOUSE_GENOME': [21, 'MT', lambda x: "chr"+x],
    'ENSEMBL_HUMAN_TRANSCRIPTOME': [190_000, None, lambda x: re.sub("ENST([0-9]*)[.][0-9]*", "ENST\\1", x)]
}

def _load_fastas_into_memory(refs, cache_path):
    # load all references into memory
    fastas = {}
    for ref in refs:
        ref_path = Path(cache_path) / _get_reference_name(ref[0])
        ref_type = ref[1]
        ref_extra_preprocessing = ref[2] if ref[2] is not None else "default"
        if ref_extra_preprocessing not in EXTRA_PREPROCESSING:
            raise ValueError(f"Unknown extra preprocessing: {ref_extra_preprocessing}")
        
        if ref_type == 'fa.gz':
            fasta = _fastagz2dict(ref_path, fasta_total=EXTRA_PREPROCESSING[ref_extra_preprocessing][0],
                                  stop_id=EXTRA_PREPROCESSING[ref_extra_preprocessing][1],
                                  region_name_transform=EXTRA_PREPROCESSING[ref_extra_preprocessing][2])
            fastas[_get_reference_name(ref[0])] = fasta
        else:
            raise ValueError(f'Unknown reference type {ref_type}')
    return fastas


def _fastagz2dict(fasta_path, fasta_total=None, stop_id=None, region_name_transform=lambda x: x):
    # load gzipped fasta into dictionary
    fasta = dict()

    with gzip.open(fasta_path, "rt") as handle:
        for record in tqdm(SeqIO.parse(handle, "fasta"), total=fasta_total):
            fasta[region_name_transform(record.id)] = str(record.seq)
        
            if stop_id and (record.id == stop_id): 
                # stop, do not read small contigs
                break
                
    return fasta

def _fill_seq_column(ref, tab):
    # fill seq column in tab
    if not all([r in ref for r in tab['region']]):
        raise ValueError(f'Some regions not found in the reference.')
    return pd.Series([ref[region][start:end] for region, start, end in zip(tab['region'], tab['start'], tab['end'])])

def _remove_and_create(path):
    # cleaning step: remove the folder and then it again
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
