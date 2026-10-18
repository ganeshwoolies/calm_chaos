# Try it: test photos

Photos to send from the live store page, so Gemini reads a shelf or a pack label and the desk acts on it.
CalmChaosRetail, its products and these photos are fictional; every photo is stamped as a test image.

## Before you start

1. Open [calm-chaos.web.app/desk](https://calm-chaos.web.app/desk) and sign in with the judge login from the submission
   form.
2. Download the photos you want from this folder: open one, then use GitHub's download button.

On a computer, the store page's photo buttons open a file picker. On a phone, you can also photograph a photo shown on
another screen.

## Shelf photos: clear a recall

1. On the desk, open **Scenarios**. Choose **yoghurt listeria** or **dinosaur choking**, then press **Publish to the test
   feed**, **Poll feeds now** and **Run the scope job now**.
2. The incident appears under **Incidents** within about two minutes. Open it and press **Approve**.
3. In the incident's store tasks, click a store id to open that store's page.
4. On a task card, press **Photograph the shelf** and choose a photo for the same recall.

| Yoghurt recall | Dinosaur recall | The photo shows | The store page answers |
|---|---|---|---|
| [clear](shelves/yoghurt_listeria_clear.jpg) | [clear](shelves/dinosaur_choking_clear.jpg) | No recalled unit left | Clear: the task closes |
| [present](shelves/yoghurt_listeria_present.jpg) | [present](shelves/dinosaur_choking_present.jpg) | Recalled units still on the shelf | Not clear: the task is issued again |
| [note](shelves/yoghurt_listeria_note.jpg) | [note](shelves/dinosaur_choking_note.jpg) | A sign saying "all clear", with units still there | Not clear |
| [blurred](shelves/yoghurt_listeria_blurred.jpg) | [blurred](shelves/dinosaur_choking_blurred.jpg) | Too blurred to check | Retake |

The incident closes, and its lessons go to Memory Bank, once every store's task is clear. Send no more than about four
shelf photos a minute: a faster one can fail, and sending it again works.

## Label photos: check a pack

On any store page, press **Photograph the label** and choose a photo.

| Photo | The pack | The store page answers |
|---|---|---|
| [muesli](labels/muesli_almond_flat.jpg) | Nutty Fields Toasted Muesli 750g: almond is on the pack but missing from the online listing | High: a label incident, with a listing fix and a QA alert |
| [kettle](labels/kettle_rcm_flat.jpg) | Hearthwell Rapid Kettle 1.7L: the RCM safety mark is missing from the pack | High: a label incident, with a hold and a supplier notice |
| [dinosaur](labels/dinosaur_battery_warning_flat.jpg) | Toddlewick Light-Up Dinosaur: the button-battery warning is missing from the pack | Critical: a label incident, with a hold and a supplier notice |
| [yoghurt](labels/yoghurt_clean_flat.jpg) | Morrowdale Vanilla Yoghurt 1kg: the label matches | No finding |

Each finding also appears on the desk's **Label checks** tab. A pack and lot open one incident; checking the same pack
again does not open a second one.

## Eval evidence

The runs behind the figures in the deck, on the same fictional data:

| File | What it is |
|---|---|
| [drafting_eval_results.html](eval/drafting_eval_results.html) | The 16-case drafting eval of 18 Oct 2026, as a readable report: drafting quality 4.94 of 5 (judged by Gemini), trajectory 1.0 (every step in order, the approval pause last) and draft format 1.0. |
| [drafting_eval_results.json](eval/drafting_eval_results.json) | The same results as data, with each case's score and the judge's reasons. |
| [drafting_eval_traces.json](eval/drafting_eval_traces.json) | The 16 drafting runs those results grade: each step, model call and draft. |
| [shelf_reading.json](eval/shelf_reading.json) | Gemini's reading of each shelf photo above, with the verdict code gave and the verdict expected: 8 of 8 match. |

The drafting eval runs offline on fixture evidence (`PSD_EVIDENCE_SOURCE=fixtures agents-cli eval run`, then
`tools/eval_gate.py`); the shelf reading comes from `PSD_SHELF_EVAL=all uv run pytest tests/integration/test_shelf_reading.py`.
