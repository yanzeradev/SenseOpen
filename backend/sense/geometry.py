import numpy as np

def _get_xy(point):
    """
    Função auxiliar para extrair X e Y, seja de um dict {'x':1, 'y':2} ou lista [1, 2].
    Isso resolve o erro TypeError no log.
    """
    if isinstance(point, dict):
        return point.get('x', 0), point.get('y', 0)
    return point[0], point[1]

def get_point_side(point, line_points):
    """Retorna 'right', 'left' ou 'on_line'."""
    if len(line_points) < 2: return 'on_line'
    
    x, y = point
    
    # Extrai coordenadas de forma segura
    x1, y1 = _get_xy(line_points[0])
    x2, y2 = _get_xy(line_points[-1])
    
    p1 = np.array([x1, y1])
    p2 = np.array([x2, y2])
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

    # Itera sobre todos os segmentos da linha desenhada
    for i in range(len(line_points) - 1):
        x1, y1 = _get_xy(line_points[i])
        x2, y2 = _get_xy(line_points[i+1])
        
        # Vetor do segmento
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0: continue

        # Projeção do ponto no segmento
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
        lx1, ly1 = _get_xy(line_points[i])
        lx2, ly2 = _get_xy(line_points[i+1])
        
        p_start = (int(lx1), int(ly1))
        p_end = (int(lx2), int(ly2))
        poly_segments.append((p_start, p_end))

    # Verifica interseção
    for p_start, p_end in poly_segments:
        # Verifica se o ponto está DENTRO do bbox
        if (x1 <= p_start[0] <= x2 and y1 <= p_start[1] <= y2) or \
           (x1 <= p_end[0] <= x2 and y1 <= p_end[1] <= y2):
            return True

        # Verifica interseção de arestas (Algoritmo CCW)
        for b_start, b_end in bbox_lines:
            def ccw(A,B,C):
                return (C[1]-A[1]) * (B[0]-A[0]) > (B[1]-A[1]) * (C[0]-A[0])
            
            if ccw(p_start,b_start,b_end) != ccw(p_end,b_start,b_end) and \
               ccw(p_start,p_end,b_start) != ccw(p_start,p_end,b_end):
                return True
    return False

def segments_intersect(p1, p2, p3, p4):
    """
    Verifica se o segmento de movimento (p1->p2) intercepta a linha virtual (p3-p4).
    p1: Ponto Anterior (Track)
    p2: Ponto Atual (Track - Bolinha Vermelha)
    p3: Inicio da Linha
    p4: Fim da Linha
    """
    def ccw(A, B, C):
        return (C[1]-A[1]) * (B[0]-A[0]) > (B[1]-A[1]) * (C[0]-A[0])

    # Garante tuplas (x, y)
    p1 = _get_xy(p1)
    p2 = _get_xy(p2)
    p3 = _get_xy(p3)
    p4 = _get_xy(p4)

    # Verifica interseção completa (ambos os segmentos devem se cruzar)
    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)

def get_side_of_segment(point, p_start, p_end):
    """
    Retorna 'right' ou 'left' do ponto em relação ao vetor (p_start -> p_end).
    """
    x, y = _get_xy(point)
    x1, y1 = _get_xy(p_start)
    x2, y2 = _get_xy(p_end)
    
    # Produto cruzado (Cross Product)
    # (x2-x1)*(y-y1) - (y2-y1)*(x-x1)
    cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
    
    if cross > 0: return 'right'
    else: return 'left'

def segments_intersect(p1, p2, p3, p4):
    """
    Verifica se o segmento (p1->p2) cruza o segmento (p3->p4).
    Retorna True se houver interseção.
    """
    def ccw(A, B, C):
        Ax, Ay = _get_xy(A)
        Bx, By = _get_xy(B)
        Cx, Cy = _get_xy(C)
        return (Cy-Ay) * (Bx-Ax) > (By-Ay) * (Cx-Ax)

    # Verifica se os pontos p1 e p2 estão em lados opostos da linha p3-p4
    # E se p3 e p4 estão em lados opostos da linha p1-p2
    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)