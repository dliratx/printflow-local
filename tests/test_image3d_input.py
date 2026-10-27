from pathlib import Path
import pytest
np=pytest.importorskip('numpy',reason='Image preprocessing tests run in the image worker environment')
from PIL import Image,ImageDraw
from printflow.image3d_input import prepare_input

def test_transparent_reference_is_cropped_padded_and_original_preserved(tmp_path):
    image=Image.new('RGBA',(160,100),(0,0,0,0));ImageDraw.Draw(image).rectangle((60,10,99,89),fill=(255,0,0,255));before=image.tobytes()
    prepared,meta=prepare_input(image,tmp_path)
    assert image.tobytes()==before and prepared.width==prepared.height
    assert meta['method']=='existing alpha' and prepared.getpixel((0,0))==(128,128,128)
    assert prepared.getpixel((prepared.width//2,prepared.height//2))==(255,0,0)

def test_no_implicit_model_download_and_empty_subject_rejected(tmp_path):
    with pytest.raises(ValueError,match='Install the local background model'):prepare_input(Image.new('RGB',(30,30)),tmp_path)
    with pytest.raises(ValueError,match='no visible subject'):prepare_input(Image.new('RGBA',(30,30),(0,0,0,0)),tmp_path)

def test_prepared_background_can_be_kept_without_model(tmp_path):
    image,meta=prepare_input(Image.new('RGB',(20,40),'red'),tmp_path,background='keep')
    assert meta['method']=='kept original background' and image.mode=='RGB'
