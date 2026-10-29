import subprocess, sys
# (персонаж, текст, pitch%, rate%, volume%, сдвиг тона, пауза после, с)
VOICE = {'T': ('anna', 1.38), 'H': ('aleksandr', 1.25)}
LINES = [
 ('T', 'Приве-е-ет!',               160, 120, 100, 1.08, 0.10),  # восторг, звонко
 ('T', 'Как дела?',                 150, 135, 100, 1.04, 0.45),  # бойко, вопрос вверх
 ('H', 'Ой!',                       140, 140,  90, 1.10, 0.25),  # испуг: его заметили
 ('H', 'Э-э... нормально.',          85,  80,  70, 0.98, 0.15),  # смущённо, тихо
 ('H', 'Меня зовут... Хамми.',      90,  85,  65, 1.00, 0.40),  # стесняется
 ('T', 'А я — Точка!',              170, 125, 100, 1.10, 0.10),  # гордо, радостно
 ('T', 'Хи-хи!',                    190, 150,  90, 1.15, 0.60),  # смешок
 ('T', 'Э-э-э... пока?',            110,  90,  85, 1.00, 0.30),  # растерянно
]
parts = []
for i, (who, text, pitch, rate, vol, shift, pause) in enumerate(LINES):
    name, base = VOICE[who]
    raw, out = f'raw{i}.wav', f'p{i}.wav'
    subprocess.run(['RHVoice-test', '-p', name, '-t', str(pitch), '-r', str(rate), '-v', str(vol), '-o', raw],
                   input=text.encode(), check=True)
    k = base * shift
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', raw, '-af',
                    f'asetrate=24000*{k:.3f},aresample=48000,atempo={min(2,max(0.5,1/k*1.15)):.3f},'
                    f'apad=pad_dur={pause}', '-ac', '1', out], check=True)
    parts.append(out)
inp = sum([['-i', p] for p in parts], [])
subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *inp, '-filter_complex',
                ''.join(f'[{i}]' for i in range(len(parts))) + f'concat=n={len(parts)}:v=0:a=1,loudnorm=I=-16',
                '-ar', '44100', '-b:a', '160k', sys.argv[1]], check=True)
