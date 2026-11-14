"""Render previews by cropping exact final atlas bytes, without redrawing art."""
from pathlib import Path
import importlib.util
import json
import subprocess
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SCRIPTS = Path('/home/agent/.codex/plugins/cache/openai-curated-remote/work-pets/0.1.6/skills/create-pet/scripts')
spec = importlib.util.spec_from_file_location('previews', SCRIPTS / 'render_animation_previews.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
atlas = Image.open(ROOT / 'final/spritesheet-extended.png').convert('RGBA')
frames_root = ROOT / 'qa/final-frames'
out = ROOT / 'qa/final-previews'
out.mkdir(parents=True, exist_ok=True)
states = list(module.ROW_DURATIONS)
all_frames, all_durations = [], []
for row, state in enumerate(states):
    destination = frames_root / state
    destination.mkdir(parents=True, exist_ok=True)
    durations = module.ROW_DURATIONS[state]
    for col, duration in enumerate(durations):
        frame = atlas.crop((192*col, 208*row, 192*(col+1), 208*(row+1)))
        frame.save(destination / f'{col:02d}.png')
        all_frames.append(frame)
        all_durations.append(duration)
subprocess.run(['python3', str(SCRIPTS/'render_animation_previews.py'), '--frames-root', str(frames_root), '--output-dir', str(out)], check=True)
module.save_preview(all_frames, all_durations, out/'all-states.gif')
transition = [Image.open(frames_root/'idle'/f'{i:02d}.png').convert('RGBA') for i in range(6)]
transition += [Image.open(frames_root/'jumping'/f'{i:02d}.png').convert('RGBA') for i in range(5)]
transition += [Image.open(frames_root/'idle'/f'{i:02d}.png').convert('RGBA') for i in range(6)]
module.save_preview(transition, module.ROW_DURATIONS['idle']+module.ROW_DURATIONS['jumping']+module.ROW_DURATIONS['idle'], out/'idle-jump-idle.gif')
looks = [atlas.crop((192*(i%8),208*(9+i//8),192*(i%8+1),208*(10+i//8))) for i in range(16)]
module.save_preview(looks, [200]*16, out/'look-loop.gif')
stills = Image.new('RGBA',(192*4,236),(245,245,245,255))
draw = ImageDraw.Draw(stills)
for col,(state,index) in enumerate([('idle',0),('running-right',2),('waving',2),('jumping',2)]):
    stills.alpha_composite(Image.open(frames_root/state/f'{index:02d}.png').convert('RGBA'),(192*col,28))
    draw.text((192*col+6,8),f'{state} / {index}',fill=(0,0,0,255))
stills.save(out/'motion-stills.png')
subprocess.run(['ffmpeg','-y','-v','error','-i',str(out/'all-states.gif'),'-vf','format=yuv420p','-movflags','+faststart',str(out/'all-states.mp4')],check=True)
decode=[]
for path in sorted(out.glob('*.gif')):
    with Image.open(path) as im:
        decode.append({'file':path.name,'frames':im.n_frames,'size':im.size})
(out/'decode.json').write_text(json.dumps(decode,indent=2))
print(json.dumps({'ok':True,'output':str(out),'decoded':decode},indent=2))
