"""
GALAGA CON HILOS  -  Programacion Concurrente, Distribuida y Paralela (HPC)
===========================================================================
Idea central: cada entidad del juego corre en SU PROPIO HILO (threading.Thread).

    Hilo principal (MainThread) -> lee el teclado y DIBUJA (pygame exige que sea aqui)
    HiloOleadas      (1)        -> crea las oleadas: lanza un hilo por cada enemigo
    HiloColisiones   (1)        -> revisa choques bala-enemigo y bala-jugador
    HiloEnemigo      (N)        -> cada enemigo se mueve, hace picadas y dispara solo
    HiloBala         (max 3)    -> cada disparo del jugador es un hilo de vida corta

Herramientas de sincronizacion usadas:
    Lock       -> protege las listas compartidas (enemigos, balas, puntaje...)
    Semaphore  -> limita a 3 las balas (hilos) del jugador al mismo tiempo
    Event      -> 'corriendo' (apagar todo) y 'activo' (pausa)
    join()     -> al salir, el hilo principal espera a que terminen los demas

El panel de la derecha muestra en vivo los hilos que existen, cuantos se han
creado y terminado, el estado del semaforo y un registro de eventos.

Controles:  <- ->  mover   |  ESPACIO disparar  |  P pausa  |  H ver ID de hilos  |  ESC salir
"""
import itertools
import math
import random
import threading
import time
from collections import deque

import pygame

# ----------------------------------------------------------------------------
# Configuracion
# ----------------------------------------------------------------------------
ANCHO_JUEGO, ALTO = 480, 640
ANCHO_PANEL = 360
FPS = 60
TICK = 1 / 60            # cada hilo se actualiza ~60 veces por segundo
MAX_BALAS = 3            # valor inicial del semaforo
# MAX_BALAS = 10            # valor inicial del semaforo

NEGRO = (8, 8, 20)
BLANCO = (235, 235, 235)
GRIS = (120, 120, 140)
VERDE = (80, 220, 120)
ROJO = (240, 80, 80)
AMARILLO = (250, 210, 70)
CIAN = (80, 200, 240)
COLORES_ENEMIGO = [(240, 80, 80), (250, 160, 60), (190, 100, 240), (80, 200, 240), (120, 230, 120)]
COLOR_TIPO = {"Principal": BLANCO, "Oleadas": AMARILLO, "Colisiones": CIAN,
              "Enemigo": ROJO, "Bala": VERDE}


# ----------------------------------------------------------------------------
# Estado compartido entre TODOS los hilos
# ----------------------------------------------------------------------------
class EstadoCompartido:
    def __init__(self):
        # Lock del juego: quien quiera leer/escribir posiciones, listas o puntaje lo toma.
        self.lock = threading.Lock()
        # Lock del panel: protege el registro de hilos y el log.
        # Regla para evitar deadlock: se puede tomar lock_panel estando dentro de lock,
        # pero NUNCA al reves.
        self.lock_panel = threading.Lock()

        self.jugador_x = ANCHO_JUEGO // 2
        self.jugador_y = ALTO - 50
        self.enemigos = []          # objetos HiloEnemigo
        self.balas = []             # objetos HiloBala
        self.balas_enemigas = []    # [x, y] (las mueve HiloColisiones)
        self.puntaje = 0
        self.vidas = 3
        self.oleada = 0
        self.game_over = False
        self.invulnerable_hasta = 0.0   # tiempo tras un golpe sin recibir dano

        self.corriendo = threading.Event()   # set = el juego sigue vivo
        self.corriendo.set()
        self.activo = threading.Event()      # set = no esta en pausa
        self.activo.set()
        self.semaforo_balas = threading.Semaphore(MAX_BALAS)

        # Datos para el monitor de hilos
        self.info_hilos = {}        # nombre -> {"tipo", "tid", "inicio"}
        self.creados = 0
        self.terminados = 0
        self.log = deque(maxlen=7)
        self.historial = deque(maxlen=150)   # cantidad de hilos vivos en el tiempo

    def registrar(self, mensaje):
        with self.lock_panel:
            self.log.append(f"{time.strftime('%H:%M:%S')} {mensaje}")


# ----------------------------------------------------------------------------
# Clase base: todos los hilos del juego heredan de aqui
# ----------------------------------------------------------------------------
class HiloJuego(threading.Thread):
    tipo = "Hilo"

    def __init__(self, estado, nombre):
        # daemon=True: si el programa principal muere, estos hilos no lo bloquean
        super().__init__(name=nombre, daemon=True)
        self.estado = estado

    def run(self):
        """Lo que hace el hilo cuando se llama a .start(). Se ejecuta en el hilo nuevo."""
        e = self.estado
        with e.lock_panel:
            e.creados += 1
            e.info_hilos[self.name] = {"tipo": self.tipo,
                                       "tid": threading.get_native_id(),  # ID real del SO
                                       "inicio": time.time()}
        try:
            self.ejecutar()                  # la logica propia de cada tipo de hilo
        finally:                             # pase lo que pase, se registra su fin
            with e.lock_panel:
                e.terminados += 1
                e.info_hilos.pop(self.name, None)

    def ejecutar(self):
        raise NotImplementedError

    def esperar_tick(self):
        """Duerme un tick (cede la CPU a otros hilos) y respeta la pausa.
        Devuelve False cuando el juego se apaga, para que el hilo salga de su ciclo."""
        time.sleep(TICK)
        while not self.estado.activo.is_set():       # pausa
            if not self.estado.corriendo.is_set():
                return False
            time.sleep(0.05)
        return self.estado.corriendo.is_set() and not self.estado.game_over


# ----------------------------------------------------------------------------
# Hilo por enemigo
# ----------------------------------------------------------------------------
class HiloEnemigo(HiloJuego):
    tipo = "Enemigo"

    def __init__(self, estado, nombre, base_x, base_y, color):
        super().__init__(estado, nombre)
        self.base_x, self.base_y = base_x, base_y   # puesto en la formacion
        self.x, self.y = float(base_x), -30.0       # entra desde arriba
        self.vx = 0.0
        self.color = color
        self.vivo = True
        self.en_picada = False

    def ejecutar(self):
        e = self.estado
        t = random.random() * 6
        proxima_picada = time.time() + random.uniform(3, 12)
        while self.vivo and self.esperar_tick():
            t += TICK
            with e.lock:                                   # seccion critica
                if not self.en_picada:
                    # Volver a la formacion y balancearse de lado a lado
                    objetivo_x = self.base_x + 25 * math.sin(t)
                    self.x += (objetivo_x - self.x) * 0.08
                    self.y += (self.base_y - self.y) * 0.05
                    if time.time() > proxima_picada:
                        self.en_picada = True
                        self.vx = (e.jugador_x - self.x) / 110   # apunta al jugador
                else:
                    self.x += self.vx
                    self.y += 4.5
                    if self.y > ALTO + 20:                   # salio por abajo: reaparece
                        self.y = -30
                        self.en_picada = False
                        proxima_picada = time.time() + random.uniform(4, 12)
                if random.random() < 0.003 + 0.0005 * e.oleada:
                    e.balas_enemigas.append([self.x, self.y + 12])
        # al salir del while el metodo termina -> el hilo muere


# ----------------------------------------------------------------------------
# Hilo por bala del jugador (vida corta: nace al disparar, muere al salir/impactar)
# ----------------------------------------------------------------------------
class HiloBala(HiloJuego):
    tipo = "Bala"

    def __init__(self, estado, nombre, x, y):
        super().__init__(estado, nombre)
        self.x, self.y = float(x), float(y)
        self.viva = True

    def ejecutar(self):
        e = self.estado
        try:
            with e.lock:
                e.balas.append(self)
            while self.viva and self.y > -10 and self.esperar_tick():
                with e.lock:
                    self.y -= 9
        finally:
            with e.lock:
                if self in e.balas:
                    e.balas.remove(self)
            e.semaforo_balas.release()      # libera el cupo -> se puede volver a disparar


# ----------------------------------------------------------------------------
# Hilo de colisiones (uno solo, vive todo el juego)
# ----------------------------------------------------------------------------
class HiloColisiones(HiloJuego):
    tipo = "Colisiones"

    def ejecutar(self):
        e = self.estado
        while self.esperar_tick():
            with e.lock:
                # 1) Balas del jugador contra enemigos
                for bala in e.balas:
                    for enemigo in e.enemigos:
                        if bala.viva and enemigo.vivo and \
                           abs(bala.x - enemigo.x) < 16 and abs(bala.y - enemigo.y) < 14:
                            bala.viva = False          # el hilo bala vera esto y terminara
                            enemigo.vivo = False       # el hilo enemigo vera esto y terminara
                            e.puntaje += 150 if enemigo.en_picada else 100
                            e.registrar(f"{bala.name} destruyo {enemigo.name}")
                e.enemigos = [en for en in e.enemigos if en.vivo]

                # 2) Balas enemigas: moverlas y ver si tocan al jugador
                quedan = []
                for b in e.balas_enemigas:
                    b[1] += 5
                    if abs(b[0] - e.jugador_x) < 14 and abs(b[1] - e.jugador_y) < 14:
                        self.perder_vida()
                    elif b[1] < ALTO:
                        quedan.append(b)
                e.balas_enemigas = quedan

                # 3) Enemigo en picada chocando con el jugador
                for en in e.enemigos:
                    if abs(en.x - e.jugador_x) < 20 and abs(en.y - e.jugador_y) < 18:
                        en.vivo = False
                        self.perder_vida()

    def perder_vida(self):
        """Se llama con e.lock ya tomado."""
        e = self.estado
        if time.time() < e.invulnerable_hasta:
            return
        e.invulnerable_hasta = time.time() + 1.5
        e.vidas -= 1
        e.registrar(f"Jugador golpeado! vidas={e.vidas}")
        if e.vidas <= 0:
            e.game_over = True
            e.registrar("GAME OVER: los hilos terminan")


# ----------------------------------------------------------------------------
# Hilo generador de oleadas (uno solo): es el que CREA hilos enemigos
# ----------------------------------------------------------------------------
class HiloOleadas(HiloJuego):
    tipo = "Oleadas"

    def ejecutar(self):
        e = self.estado
        while self.esperar_tick():
            with e.lock:
                vacio = not e.enemigos
            if not vacio:
                continue
            time.sleep(1.0)
            e.oleada += 1
            filas = min(2 + e.oleada // 2, 5)
            e.registrar(f"Oleada {e.oleada}: creando {filas * 8} hilos")
            for f in range(filas):
                for c in range(8):
                    enemigo = HiloEnemigo(e, f"Enemigo-{e.oleada}.{f}{c}",
                                          70 + c * 48, 80 + f * 42,
                                          COLORES_ENEMIGO[f % len(COLORES_ENEMIGO)])
                    with e.lock:
                        e.enemigos.append(enemigo)
                    enemigo.start()            # <- aqui nace el hilo
                    time.sleep(0.04)           # entrada escalonada


# ----------------------------------------------------------------------------
# Acciones del hilo principal
# ----------------------------------------------------------------------------
contador_balas = itertools.count(1)


def disparar(estado):
    # acquire(blocking=False): si no hay cupo NO se queda esperando (no congela el juego)
    if estado.semaforo_balas.acquire(blocking=False):
    # if estado.semaforo_balas.acquire():
        HiloBala(estado, f"Bala-{next(contador_balas)}",
                 estado.jugador_x, estado.jugador_y - 18).start()
    else:
        estado.registrar("Semaforo en 0: espera un cupo")


# ----------------------------------------------------------------------------
# Dibujo
# ----------------------------------------------------------------------------
def dibujar_juego(pantalla, estado, fuentes, estrellas, ver_ids):
    f_peq, f_med, f_grande = fuentes
    pantalla.fill(NEGRO, (0, 0, ANCHO_JUEGO, ALTO))
    for s in estrellas:
        s[1] = (s[1] + s[2]) % ALTO
        pantalla.set_at((int(s[0]), int(s[1])), GRIS)

    # Tomamos una "foto" del estado con el lock y dibujamos sin bloquear a los demas
    with estado.lock:
        enemigos = [(en.x, en.y, en.color, en.name) for en in estado.enemigos]
        balas = [(b.x, b.y, b.name) for b in estado.balas]
        balas_en = [tuple(b) for b in estado.balas_enemigas]
        jx, jy = estado.jugador_x, estado.jugador_y
        puntaje, vidas, oleada, game_over = estado.puntaje, estado.vidas, estado.oleada, estado.game_over
    with estado.lock_panel:
        tids = {n: d["tid"] for n, d in estado.info_hilos.items()}

    for x, y, color, nombre in enemigos:
        pygame.draw.polygon(pantalla, color, [(x - 13, y - 6), (x, y - 11), (x + 13, y - 6),
                                              (x + 8, y + 8), (x - 8, y + 8)])
        pygame.draw.circle(pantalla, NEGRO, (int(x - 4), int(y - 2)), 2)
        pygame.draw.circle(pantalla, NEGRO, (int(x + 4), int(y - 2)), 2)
        if ver_ids and nombre in tids:
            pantalla.blit(f_peq.render(str(tids[nombre]), True, BLANCO), (x - 14, y - 26))
    for x, y, nombre in balas:
        pygame.draw.rect(pantalla, VERDE, (x - 2, y - 7, 4, 12))
        if ver_ids and nombre in tids:
            pantalla.blit(f_peq.render(str(tids[nombre]), True, VERDE), (x + 5, y - 6))
    for x, y in balas_en:
        pygame.draw.circle(pantalla, AMARILLO, (int(x), int(y)), 3)

    parpadeo = time.time() < estado.invulnerable_hasta and int(time.time() * 10) % 2
    if not parpadeo:
        pygame.draw.polygon(pantalla, CIAN, [(jx, jy - 18), (jx - 15, jy + 12), (jx, jy + 5), (jx + 15, jy + 12)])
    if ver_ids:
        pantalla.blit(f_peq.render(f"Main {threading.main_thread().native_id}", True, CIAN), (jx - 30, jy + 16))

    pantalla.blit(f_med.render(f"PUNTOS {puntaje}", True, BLANCO), (10, 8))
    pantalla.blit(f_med.render(f"OLEADA {oleada}", True, BLANCO), (190, 8))
    pantalla.blit(f_med.render("VIDAS " + "A" * max(vidas, 0), True, CIAN), (360, 8))

    centro = ANCHO_JUEGO // 2
    if game_over:
        t = f_grande.render("GAME OVER", True, ROJO)
        pantalla.blit(t, t.get_rect(center=(centro, ALTO // 2)))
        t = f_med.render("ESC para salir", True, BLANCO)
        pantalla.blit(t, t.get_rect(center=(centro, ALTO // 2 + 40)))
    elif not estado.activo.is_set():
        t = f_grande.render("PAUSA", True, AMARILLO)
        pantalla.blit(t, t.get_rect(center=(centro, ALTO // 2)))


def dibujar_panel(pantalla, estado, fuentes):
    f_peq, f_med, _ = fuentes
    x0 = ANCHO_JUEGO
    pantalla.fill((18, 18, 32), (x0, 0, ANCHO_PANEL, ALTO))
    pygame.draw.line(pantalla, CIAN, (x0, 0), (x0, ALTO), 2)
    x = x0 + 12
    y = 10

    def linea(texto, color=BLANCO, fuente=f_peq, salto=17):
        nonlocal y
        pantalla.blit(fuente.render(texto, True, color), (x, y))
        y += salto

    # Leer datos de los hilos (threading.enumerate() da TODOS los hilos vivos del proceso)
    vivos = threading.enumerate()
    with estado.lock_panel:
        info = dict(estado.info_hilos)
        creados, terminados = estado.creados, estado.terminados
        log = list(estado.log)
    estado.historial.append(len(vivos))

    conteo = {"Principal": 1}
    for h in vivos:
        tipo = info.get(h.name, {}).get("tipo")
        if tipo:
            conteo[tipo] = conteo.get(tipo, 0) + 1

    linea("MONITOR DE HILOS", CIAN, f_med, 24)
    linea(f"Vivos ahora (active_count): {threading.active_count()}", AMARILLO)
    linea(f"Creados: {creados}   Terminados: {terminados}")
    estado_txt = "PAUSADO (Event activo=clear)" if not estado.activo.is_set() else "corriendo"
    linea(f"Estado: {estado_txt}", GRIS, salto=22)

    # Conteo por tipo
    for tipo in ["Principal", "Oleadas", "Colisiones", "Enemigo", "Bala"]:
        n = conteo.get(tipo, 0)
        pygame.draw.rect(pantalla, COLOR_TIPO[tipo], (x, y + 3, 10, 10))
        pantalla.blit(f_peq.render(f"{tipo:<11}{n:>3}", True, BLANCO), (x + 16, y))
        pygame.draw.rect(pantalla, COLOR_TIPO[tipo], (x + 140, y + 4, min(n * 4, 190), 8))
        y += 17

    # Semaforo
    y += 4
    libres = estado.semaforo_balas._value   # atributo interno, solo para mostrarlo
    linea(f"Semaforo balas: {libres}/{MAX_BALAS} libres")
    for i in range(MAX_BALAS):
        color = VERDE if i < libres else ROJO
        pygame.draw.rect(pantalla, color, (x + i * 26, y, 20, 12))
    y += 22

    # Grafica de hilos vivos en el tiempo
    linea("Hilos vivos en el tiempo:", GRIS)
    alto_g, ancho_g = 50, ANCHO_PANEL - 30
    pygame.draw.rect(pantalla, (35, 35, 55), (x, y, ancho_g, alto_g))
    hist = list(estado.historial)
    tope = max(max(hist), 10)
    puntos = [(x + i * ancho_g / 150, y + alto_g - v / tope * (alto_g - 4)) for i, v in enumerate(hist)]
    if len(puntos) > 1:
        pygame.draw.lines(pantalla, AMARILLO, False, puntos, 2)
    pantalla.blit(f_peq.render(str(tope), True, GRIS), (x + ancho_g - 22, y))
    y += alto_g + 8

    # Lista de hilos
    linea("Nombre               TID      edad", GRIS)
    ahora = time.time()
    lista = [("MainThread", "Principal", threading.main_thread().native_id, None)]
    for nombre, d in info.items():
        lista.append((nombre, d["tipo"], d["tid"], ahora - d["inicio"]))
    prioridad = {"Principal": 0, "Oleadas": 1, "Colisiones": 2, "Bala": 3, "Enemigo": 4}
    lista.sort(key=lambda t: prioridad.get(t[1], 9))
    for nombre, tipo, tid, edad in lista[:10]:
        edad_txt = "-" if edad is None else f"{edad:5.1f}s"
        linea(f"{nombre[:19]:<19} {tid:<8} {edad_txt}", COLOR_TIPO.get(tipo, BLANCO), salto=15)
    if len(lista) > 10:
        linea(f"... y {len(lista) - 10} hilos mas", GRIS, salto=15)

    # Log de eventos
    y = ALTO - 7 * 15 - 40
    linea("Eventos:", GRIS)
    for msg in log:
        linea(msg[:44], BLANCO, salto=15)
    y = ALTO - 20
    linea("ESPACIO dispara | P pausa | H ver IDs", GRIS)


# ----------------------------------------------------------------------------
# Programa principal (hilo principal)
# ----------------------------------------------------------------------------
def main():
    pygame.init()
    pantalla = pygame.display.set_mode((ANCHO_JUEGO + ANCHO_PANEL, ALTO))
    pygame.display.set_caption("Galaga con hilos - HPC")
    reloj = pygame.time.Clock()
    fuentes = (pygame.font.SysFont("consolas,dejavusansmono,monospace", 13),
               pygame.font.SysFont("consolas,dejavusansmono,monospace", 16, bold=True),
               pygame.font.SysFont("consolas,dejavusansmono,monospace", 40, bold=True))
    estrellas = [[random.randint(0, ANCHO_JUEGO - 1), random.randint(0, ALTO - 1), random.uniform(0.3, 1.5)]
                 for _ in range(70)]

    estado = EstadoCompartido()
    estado.registrar("MainThread: iniciando hilos")
    # Hilos que viven todo el juego
    HiloColisiones(estado, "Colisiones").start()
    HiloOleadas(estado, "Oleadas").start()

    ver_ids = False
    while estado.corriendo.is_set():
        for evento in pygame.event.get():
            if evento.type == pygame.QUIT:
                estado.corriendo.clear()
            elif evento.type == pygame.KEYDOWN:
                if evento.key == pygame.K_ESCAPE:
                    estado.corriendo.clear()
                elif evento.key == pygame.K_p:
                    if estado.activo.is_set():
                        estado.activo.clear()
                        estado.registrar("Pausa: los hilos esperan")
                    else:
                        estado.activo.set()
                        estado.registrar("Reanudar: los hilos siguen")
                elif evento.key == pygame.K_h:
                    ver_ids = not ver_ids
                elif evento.key == pygame.K_SPACE and estado.activo.is_set() and not estado.game_over:
                    disparar(estado)

        if estado.activo.is_set() and not estado.game_over:
            teclas = pygame.key.get_pressed()
            with estado.lock:
                if teclas[pygame.K_LEFT]:
                    estado.jugador_x = max(20, estado.jugador_x - 6)
                if teclas[pygame.K_RIGHT]:
                    estado.jugador_x = min(ANCHO_JUEGO - 20, estado.jugador_x + 6)

        dibujar_juego(pantalla, estado, fuentes, estrellas, ver_ids)
        dibujar_panel(pantalla, estado, fuentes)
        pygame.display.flip()
        reloj.tick(FPS)

    # Cierre ordenado: avisar a todos los hilos y esperarlos con join()
    estado.activo.set()                       # por si estaba en pausa
    for hilo in threading.enumerate():
        if hilo is not threading.main_thread():
            hilo.join(timeout=1)
    print(f"Hilos creados en total: {estado.creados} | terminados: {estado.terminados}")
    pygame.quit()


if __name__ == "__main__":
    main()
