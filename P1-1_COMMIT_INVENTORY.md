# P1-1 · `t_5ea3d7e3` — inventario de los 6 commits de kernel, y estado de preservacion

Storm padre `t_b50c4dc1` · Plan `SPRINT_R4_PLAN.md` §4 P1-1 · Repo `/Users/igoni/.hermes/hermes-agent`
Medido: 2026-10-05. **Ningun commit de este inventario se ha modificado, rebaseado ni mergeado.**

---

## 0. Estado de preservacion — PRIMERO, porque es lo urgente

**Las dos ramas estan en `fork` (IkerGoni/hermes-agent, publico, fork de NousResearch).**

```
$ git ls-remote fork 'refs/heads/fix/t_5ea3d7e3*' 'refs/heads/fix/triage-exit-and-board-counts-pr'
6a20ed05b16262ea8f14ebb91d8ff7e39d8ab13c	refs/heads/fix/t_5ea3d7e3-triage-escape
f1b68b26b5be13630a3af0b0afd66139dbc6bd82	refs/heads/fix/triage-exit-and-board-counts-pr
```

Los dos tips remotos coinciden con los locales. Ninguno de los 8 commits esta en `origin/main`
(`merge-base --is-ancestor` = falso para los 8 tras `git fetch origin`), y `unpinned_kanban_db_path`
no aparece en `origin/main` bajo `hermes_cli/` (si en la rama de triage).

**Como se hizo (nota de credenciales).** El remote `fork` (SSH) **no** funciona en esta maquina:

```
$ git push --no-verify fork fix/t_5ea3d7e3-triage-escape:refs/heads/fix/t_5ea3d7e3-triage-escape
ERROR: Permission to IkerGoni/hermes-agent.git denied to NiceBdsmer.
```

La clave SSH de la maquina resuelve a la cuenta `NiceBdsmer`, no a `IkerGoni`. Se resolvio con el
remote `fork-https` + el credential helper de `gh` (`gh auth setup-git`, ya configurado como
protocolo https, scopes `repo workflow`). **Quien use SSH contra `fork` va a perder el tiempo, y
en el peor caso Cree que ha pusheado cuando no.** No he cambiado la configuracion de SSH: eso no
es de esta card.

---

## 1. El inventario que la card exige

Seis commits en `fix/t_5ea3d7e3-triage-escape`, ninguno en `origin/main`. Medidos uno a uno con
`git show --stat` (nunca `diff main..rama`, que aqui reporta 4080 ficheros por el desfase de
1206 commits de `main` local — ver `SPRINT_R4_PLAN.md` §1).

### 1.1 `6a20ed05b16` — **dueno: `t_5ea3d7e3`** (esta card)

```
fix(kanban): give triage cards an exit and fix board counts under a DB pin
 hermes_cli/kanban.py           | 15 ++++++
 hermes_cli/kanban_boards.py    | 13 +++--
 hermes_cli/kanban_db.py        | 47 ++++++++++++++----
 hermes_cli/kanban_parser.py    |  3 +-
 tests/hermes_cli/test_kanban_boards.py | 38 +++++++++++
 tests/hermes_cli/test_kanban_db.py     | 87 ++++++++++++++++++
 6 files changed, 191 insertions(+), 12 deletions(-)
```

Es el unico commit de la rama que toca `unpinned_kanban_db_path` (en `kanban_boards.py` y
`kanban_db.py`). 125 de las 191 lineas son tests. **Dueno confirmado: la card que origina la
rama. No se mueve.**

### 1.2 Los 4 commits que **ninguna card de ningun board** nombra

Ninguno aparece en `t_5ea3d7e3`, ni en `t_ec8b59f1`, ni en `t_1f64d6e2` (PR #4), ni en
`t_97cb2430` (PR #5). Buscados por hash y por mensaje en las bases de board de este kanban.
Veredicto: **huerfano desconocido.** No se portan; portarlos es un si/no de Iker
(`SPRINT_R4_PLAN.md` §5).

| commit | mensaje | ficheros | que es |
|---|---|---|---|
| `91494119ec5` | `fix(tools): select a dependency generation before a spawned child works` | `tools/bot_mode_dm.py` (+5), `tools/neutts_synth.py` (+16) | seleccion de generacion de dependencias antes de un hijo spawneado |
| `b59a21bf66f` | `test(tools): guard bare-script spawns against missing dependency activation` | `scripts/check_bare_script_activation.py` (+346), `tests/tools/test_bot_mode_dm.py` (+136), `.github/workflows/lint.yml` (+11) | guarda de CI: script invocado sin activacion de venv |
| `0d6f48e2d8f` | `fix(kanban): make the worker spawn argv self-contained` | `hermes_cli/kanban_db_dispatch.py` (+52), `tests/hermes_cli/test_kanban_db.py` (+109) | argv del spawn autodefinitivo |
| `cdb637d02c3` | `test(kanban): make the argv self-containment tests non-vacuous` | `tests/hermes_cli/test_kanban_db.py` (+18/−2) | los tests de arriba dejaban pasar sin comprobar |
| `1d022d3d523` | `test(launchd): pin that the plist does NOT pin HERMES_BIN` | `tests/hermes_cli/test_gateway_service.py` (+85) | test que fija que el plist **no** fija `HERMES_BIN` |

**Esto son 5 commits, no 4.** El cuerpo de la card y el plan cuentan 4; el quinto es
`1d022d3d523`, y por que importa no es cosmetico: es el unico de los cinco que **contradice** el
resto. `91494119ec5` selecciona una generacion de dependencias para el hijo spawneado, y
`1d022d3d523` fija que el plist **no** debe fijar `HERMES_BIN`. Son dos politicas opuestas de
resolucion de interprete. Portar uno sin el otro es elegir sin saber; portarlos ambos es
aceptar las dos. **Por eso el inventario no puede cerrarse como "los 4 de los que habla el
plan": son 5, en conflicto entre si, y ninguno tiene dueno.**

### 1.3 La segunda rama — `fix/triage-exit-and-board-counts-pr`

2 commits, ninguno en `origin/main`:

| commit | mensaje | dueno | veredicto |
|---|---|---|---|
| `95636f30dbb` | `fix(kanban): give triage cards an exit...` | `t_5ea3d7e3` (patch-id identico `49b7ae98` a `6a20ed05b16`) | **duplicado de 1.1.** No necesita card propia |
| `f1b68b26b5b` | `fix(tui): a missing runtime limit must not render as max_runtime=0s` | `t_ec8b59f1` / PR #1 | **NO es PR #1. Ver §2** |

---

## 2. `f1b68b26b5b` no es el trabajo de PR #1: es PR #1 **mas una reversal parcial de `main`**

Patch-id de `f1b68b26b5b` = `9df4059c96acf7652d2c1dbb587f7cf2b10a7560`.
Patch-id de PR #1 (`f2cae6c95a4`) = `9f5d49c56c37a6b6b17e7a3f570bfea5badc3971`.
**Distintos.** El plan (y la card padre de `t_ec8b59f1`) los tratan como el mismo trabajo.

La diferencia no es ruido de contexto, son **3 hunks de borrado de codigo vivo**:

```
$ git show f1b68b26b5b -- tui_gateway/session_notifications.py   # 4 hunks
@@ -311,10 +311,18 @@ _kb_completed              <- el fix correcto, identico a PR #1
@@ -456,15 +464,6  @@ _notif_poll_kanban_scoped   <- BORRA _background_notifications_off()
@@ -479,16 +478,8  @@ _notif_dispatch_event        <- degrada el kwargs de async_delegation
@@ -549,10 +540,6  @@ _notif_handle_event         <- BORRA el gate de opt-out
```

Y ese codigo **existe hoy en `origin/main`**:

```
$ git grep -c "_background_notifications_off" <ref> -- tui_gateway/session_notifications.py
95636f30dbb  (su propio padre) : 2
f1b68b26b5b                     : 0     <- borrada
f2cae6c95a4  (PR #1)            : 2
origin/main                     : 2
```

Lo que se pierde si `fix/triage-exit-and-board-counts-pr` se mergea tal cual: la funcion de
opt-out de notificaciones de proceso (`display.background_process_notifications: off`) y el
gate que impide que un evento `async_delegation` se pinte como aviso de proceso.

**Por que la razon de ser de la rama lo Provoco.** El padre `95636f30dbb` esta **1206 commits
atras** de `origin/main`. `git apply` de ese parche sobre el arbol actual falla con
`does not match index`. Git no dijo "esto ya esta en main": dijo "esto no aplica aqui", y el
commit se llevo igualmente la eliminacion. Un cherry-pick de `f1b68b26b5b` **no** es seguro, y un
rebase de la rama **no** lo arregla.

**Veredicto: `fix/triage-exit-and-board-counts-pr` no se debe integrar tal cual.** PR #1
(`f2cae6c95a4`, abierto, base `base/upstream-main-2026-10-04`) es la version correcta y ya
contiene el unico hunk que la rama quiere. Si el fix del TUI hace falta, se toma de ahi.

---

## 3. Tests (los tres ficheros que pide la card)

Con `scripts/run_tests.sh` (el runner canonico de AGENTS.md, con `HERMES_PYTHON` apuntando a
`/Users/igoni/.hermes/hermes-agent/.venv/bin/python`, pytest 9.1.1 / py 3.14.7), en el worktree del
tip de triage `6a20ed05b16`:

| fichero | resultado |
|---|---|
| `tests/hermes_cli/test_kanban_boards.py` | verde (12.15s) |
| `tests/hermes_cli/test_kanban_cli.py` | verde (2.96s) |
| `tests/hermes_cli/test_kanban_db.py` | 1 fallo, 52 pass |

**El fallo pre-existente que la card declara, confirmado por comparacion y no por suposicion.**
La card dice que `test_infrastructure_spawn_refusal_never_charges_the_card` "reproducia igual en
main". Medido en dos commits distintos:

- tip de triage `6a20ed05b16`: `assert ['t_7981f388'] == []` (`test_kanban_db.py:578`)
- **padre sin ninguno de los 6 commits**, `02f57212a4`, en un worktree desechable creado y
  borrado para la medicion: `assert ['t_2f85ac28'] == []`, mismo fichero y misma linea

Mismo fallo, misma asercion, distinto id de tarea. **El fallo no lo causa ninguno de los 6
commits.** Es una asercion sobre `res.auto_blocked` en `dispatch_once` que ya estaba rota antes de
la rama; queda anotada y **no** se arregla aqui (no-goal de la card).

---

## 4. Que falta para cerrar la card

El inventario **esta escrito y es este documento**. Lo que falta es solo una decision de Iker, y
son tres:

1. **Los 5 commits sin dueno** (§1.2): se portan, se descartan, o se dejan en la rama preservada
   y sin integrar. Y si se portan, **cual de las dos politicas opuestas de interprete**
   (`91494119ec5` vs `1d022d3d523`).
2. **`f1b68b26b5b`** (§2): confirmacion de que la rama no se integra tal cual por la reversal
   parcial, y que PR #1 es la via. Esto no lo decido yo: el merge es de Iker, y el plan (§5) ya
   dice que ninguna card del sprint mergea nada.
3. **`6a20ed05b16`**: sigue sin estar en ningun `main`. Esta card lo preserva y lo mide; su
   integracion es trabajo aparte.

## 5. No-goals respetados

**No se ha rebaseado, mergeado ni modificado codigo.** Las dos ramas estan byte-identicas a como
estaban antes de esta card (tips verificados al final). Las unicas escrituras en disco han sido
cinco scripts de sondeo desechables en el worktree de esta card y este documento.