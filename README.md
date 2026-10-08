# Galaga con hilos

Galaga en Python (pygame-ce) donde **cada enemigo y cada bala es un `threading.Thread`**. A la derecha de la pantalla hay un **monitor de hilos en vivo**: hilos activos, creados y terminados, estado del semáforo, TID de cada hilo y registro de eventos.

Proyecto de **Programación Concurrente, Distribuida y Paralela** · Carlos Enrique Álape Hernández.

## Ejecutar

**Opción 1: ejecutable (Windows, sin instalar nada).**
Descarga `GalagaHilos.exe` desde [Releases](../../releases) y ábrelo con doble clic.
El ejecutable no está firmado, así que Windows puede mostrar "Windows protegió su PC". En ese caso, elige *Más información → Ejecutar de todas formas*.

**Opción 2: con Python 3.**

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
python galaga_hilos.py
```

Al cerrar el juego, la terminal muestra cuántos hilos se crearon y cuántos terminaron.

## Controles

| Tecla | Acción |
|---|---|
| ← → | Mover la nave |
| ESPACIO | Disparar (crea un hilo `HiloBala`) |
| P | Pausar / reanudar |
| H | Mostrar el ID de hilo del sistema operativo (TID) sobre cada personaje |
| ESC | Salir |

## Hilos y sincronización

| Hilo | Cantidad | Qué hace |
|---|---|---|
| `MainThread` | 1 | Lee el teclado y dibuja (pygame solo funciona en el hilo principal) |
| `HiloOleadas` | 1 | Crea las oleadas: lanza un hilo por enemigo |
| `HiloColisiones` | 1 | Revisa los choques y maneja el puntaje y las vidas |
| `HiloEnemigo` | 16 a 40 | Cada enemigo se mueve, hace picadas y dispara por su cuenta |
| `HiloBala` | máx. 3 | Cada disparo del jugador es un hilo de vida corta |

- **`Lock`** protege el estado compartido. Se usan dos locks, que siempre se adquieren en el mismo orden para evitar *deadlock*.
- **`Semaphore(3)`** limita las balas simultáneas.
- **`Event`** maneja la pausa y el apagado de todos los hilos.
- **`join()`** cierra los hilos de forma ordenada al salir.

## Documentación

La explicación completa está en [DOCUMENTACION.md](DOCUMENTACION.md), y también en PDF: [DOCUMENTACION.pdf](DOCUMENTACION.pdf). Incluye:

- diagramas de arquitectura, de ciclo de vida y de secuencia;
- el detalle de cada mecanismo de sincronización;
- la relación con el GIL;
- los experimentos y las preguntas frecuentes.
