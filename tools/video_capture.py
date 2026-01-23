import cv2
import ffmpeg
import numpy as np
import sys

# --- DADOS DA CÂMERA ---
ip = '127.0.0.1'
port = '47933'
user = 'admin'
pwd = 'senha' 
channel = '1'  # Canal padrão para câmeras IP

# --- PASSO 1: AUTODETECÇÃO ---
def buscar_conexao(ip, user, pwd):
    # Lista expandida para cobrir Câmera IP (channel 1) e DVR (channel 2+)
    configs = [
        # (Nome, Caminho, Protocolo)
        ('Yoosee/udp', '/onvif1', 'udp'),
        ('Yoosee/tcp', '/onvif1', 'tcp'),
        ('Intelbras/tcp', f'/cam/realmonitor?channel={channel}&subtype=0', 'tcp'),
        ('Intelbras/udp', f'/cam/realmonitor?channel={channel}&subtype=0', 'udp'),
        ('Yoosee Nova', '/live/ch0', 'udp'),
        ('Yoosee Nova', '/live/ch0', 'tcp'),
    ]
    
    print(f"🕵️ Procurando sinal da câmera {ip}:{port}...")
    print(f"👤 Usuário: {user} | Senha: {pwd}")
    
    for nome, path, proto in configs:
        url = f"rtsp://{user}:{pwd}@{ip}:{port}{path}"
        print(f"👉 Testando {nome} [{proto.upper()}]: {path} ...", end=" ")
        
        try:
            # Aumentei o timeout para 5 segundos (5000000) para garantir
            probe = ffmpeg.probe(url, rtsp_transport=proto, timeout='5000000')
            
            stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
            if stream:
                w = int(stream['width'])
                h = int(stream['height'])
                print(f"✅ SUCESSO! ({w}x{h})")
                return url, proto, w, h
                
        except ffmpeg.Error as e:
            # --- AQUI ESTÁ A MÁGICA: Captura o erro real ---
            erro_msg = e.stderr.decode('utf8') if e.stderr else str(e)
            
            if "401 Unauthorized" in erro_msg:
                print("❌ ERRO DE SENHA (401)")
            elif "Connection refused" in erro_msg:
                print("❌ PORTA FECHADA/RECUSADA")
            elif "No route to host" in erro_msg:
                print("❌ IP INACESSÍVEL")
            elif "Not Found" in erro_msg or "404" in erro_msg:
                print("❌ CAMINHO ERRADO (404)")
            elif "Invalid data" in erro_msg:
                print("❌ PROTOCOLO INVÁLIDO (Tente outro TCP/UDP)")
            else:
                # Imprime um trecho do erro para análise
                print(f"❌ FALHA: {erro_msg.splitlines()[-1]}")
            continue
            
    return None, None, 0, 0

# Executa a busca
url_final, protocolo_final, width, height = buscar_conexao(ip, user, pwd)

if not url_final:
    print("\n❌ RESUMO DO ERRO:")
    print("1. Se deu 'ERRO DE SENHA': A senha está errada para esse IP.")
    print("2. Se deu 'IP INACESSÍVEL': O IP mudou ou o PC não alcança a câmera.")
    print("3. Se deu 'PORTA FECHADA': A câmera usa outra porta (não é 554).")
    sys.exit()

# --- PASSO 2: ABRIR VÍDEO ---
print(f"\n🎥 Abrindo Stream...")
print(f"URL: {url_final}")

process = (
    ffmpeg
    .input(url_final, 
           rtsp_transport=protocolo_final, 
           buffer_size='2048000') # Buffer dobrado
    .output('pipe:', format='rawvideo', pix_fmt='bgr24')
    .run_async(pipe_stdout=True)
)

window_name = f"Camera Universal"
cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

while True:
    try:
        in_bytes = process.stdout.read(width * height * 3)
        if not in_bytes:
            break
        frame = np.frombuffer(in_bytes, np.uint8).reshape([height, width, 3])
        cv2.imshow(window_name, frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    except Exception as e:
        print(f"Erro display: {e}")
        break

process.wait()
cv2.destroyAllWindows()