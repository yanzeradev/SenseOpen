import numpy as np

def get_point_side(point, line_points):
    """Retorna 'right', 'left' ou 'on_line'."""
    if len(line_points) < 2: return 'on_line'
    x, y = point
    p1 = np.array([line_points[0]['x'], line_points[0]['y']])
    p2 = np.array([line_points[-1]['x'], line_points[-1]['y']])
    p = np.array([x, y])
    cross = np.cross(p2 - p1, p - p1)
    if cross > 20: return 'right'
    elif cross < -20: return 'left'
    return 'on_line'

def get_closest_segment_side(point, line_points):
    """
    Descobre de que lado da polilinha o ponto está.
    Retorna: 'right', 'left' ou 'unknown'
    """
    if len(line_points) < 2: return 'unknown'
    
    px, py = point
    min_dist_sq = float('inf')
    side = 'unknown'

    # Itera sobre todos os segmentos da linha desenhada (ponto A até ponto B)
    for i in range(len(line_points) - 1):
        p1 = line_points[i]
        p2 = line_points[i+1]
        
        x1, y1 = p1['x'], p1['y']
        x2, y2 = p2['x'], p2['y']
        
        # Vetor do segmento
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0: continue

        # Projeção do ponto no segmento para achar a distância
        t = ((px - x1) * dx + (py - y1) * dy) / (dx*dx + dy*dy)
        t = max(0, min(1, t)) # Clampa entre 0 e 1
        
        # Ponto mais próximo na linha
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy
        
        # Distância ao quadrado
        dist_sq = (px - closest_x)**2 + (py - closest_y)**2
        
        # Se achamos um segmento mais próximo, calculamos o lado relativo a ELE
        if dist_sq < min_dist_sq:
            min_dist_sq = dist_sq
            
            # Produto vetorial para saber esquerda/direita
            cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
            
            if cross > 0: side = 'right'
            else: side = 'left'

    return side

def bbox_intersects_line(bbox, line_points):
    """Verifica se o BBOX toca a linha (interseção de segmentos)."""
    if len(line_points) < 2: return False
    x1, y1, x2, y2 = map(int, bbox)
    
    # Define as 4 linhas do BBox
    bbox_lines = [
        ((x1, y1), (x2, y1)), # Top
        ((x2, y1), (x2, y2)), # Right
        ((x2, y2), (x1, y2)), # Bottom
        ((x1, y2), (x1, y1))  # Left
    ]
    
    # Define segmentos da linha desenhada pelo usuário
    poly_segments = []
    for i in range(len(line_points) - 1):
        p_start = (int(line_points[i]['x']), int(line_points[i]['y']))
        p_end = (int(line_points[i+1]['x']), int(line_points[i+1]['y']))
        poly_segments.append((p_start, p_end))

    # Verifica interseção
    for p_start, p_end in poly_segments:
        # Verifica se o ponto está DENTRO do bbox
        if (x1 <= p_start[0] <= x2 and y1 <= p_start[1] <= y2) or \
           (x1 <= p_end[0] <= x2 and y1 <= p_end[1] <= y2):
            return True

        # Verifica interseção de arestas
        for b_start, b_end in bbox_lines:
            def ccw(A,B,C):
                return (C[1]-A[1]) * (B[0]-A[0]) > (B[1]-A[1]) * (C[0]-A[0])
            if ccw(p_start,b_start,b_end) != ccw(p_end,b_start,b_end) and \
               ccw(p_start,p_end,b_start) != ccw(p_start,p_end,b_end):
                return True
    return False