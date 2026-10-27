"""Local foreground preparation for TripoSR. No request-time model downloads."""
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps

QUALITY = {'draft':128, 'balanced':192, 'detail':256}
_segmenter = None

def prepare_input(source, weights:Path, background='remove', foreground_ratio=.85):
    global _segmenter
    if background not in {'remove','keep'}:raise ValueError('Choose remove or keep for the image background')
    if not .65<=foreground_ratio<=.95:raise ValueError('Foreground ratio must be between 0.65 and 0.95')
    source=ImageOps.exif_transpose(source).convert('RGBA');source.thumbnail((1024,1024))
    alpha=source.getchannel('A');has_alpha=alpha.getextrema()[0]<255
    method='existing alpha' if has_alpha else 'kept original background'
    if background=='remove' and not has_alpha:
        path=Path(weights)/'u2net.onnx'
        if not path.is_file():raise ValueError('Install the local background model, or supply a transparent PNG')
        import onnxruntime as ort
        if _segmenter is None:
            options=ort.SessionOptions();options.intra_op_num_threads=4
            _segmenter=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        rgb=np.asarray(source.convert('RGB').resize((320,320),Image.Resampling.LANCZOS),dtype=np.float32)
        rgb/=max(float(rgb.max()),1e-6)
        normalized=(rgb-np.array([.485,.456,.406],dtype=np.float32))/np.array([.229,.224,.225],dtype=np.float32)
        output=_segmenter.run(None,{_segmenter.get_inputs()[0].name:normalized.transpose(2,0,1)[None]})[0][0,0]
        span=float(output.max()-output.min())
        if span<1e-6:raise ValueError('Could not separate the subject. Try a transparent image or a clearer background')
        mask=np.clip((output-output.min())/span,0,1)
        alpha=Image.fromarray((mask*255).astype('uint8')).resize(source.size,Image.Resampling.LANCZOS)
        source.putalpha(alpha);method='U2Net local foreground segmentation'
    if has_alpha or background=='remove':
        bounds=alpha.point(lambda x:255 if x>24 else 0).getbbox()
        if not bounds:raise ValueError('The reference image contains no visible subject')
        source=source.crop(bounds)
        side=max(1,round(max(source.size)/foreground_ratio))
    else:side=max(source.size)
    canvas=Image.new('RGBA',(side,side),(128,128,128,255))
    canvas.alpha_composite(source,((side-source.width)//2,(side-source.height)//2))
    return canvas.convert('RGB'),{'method':method,'foreground_ratio':foreground_ratio,'background_mode':background}
