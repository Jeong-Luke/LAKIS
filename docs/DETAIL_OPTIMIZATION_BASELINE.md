# LAKIS DETAIL optimization baseline

## Fixed benchmark contract

- Hardware reference: RTX 3080 Ti 12 GB
- Mode: T2I, fixed seed, composition disabled
- Resolution: 1056 x 1472
- Initial sampler: 30 steps, CFG 5, Euler Ancestral, Normal
- HighRez: Anima Turbo LoRA v0.2, strength 1.0, 3 steps, CFG 1
- LoRA stack: preserve the same eight enabled LoRAs for every comparison
- Runtime isolation: clear the ComfyUI model cache after every generation
- Run order: alternate control and candidate; use three completed runs per variant

## Measured reference (2026-09-06)

| Path | Time | Increment over FAST |
| --- | ---: | ---: |
| FAST mean (3 runs) | 57.96 s | - |
| Face detailer only | 103.74 s | +45.78 s |
| Eye detailer only | 98.84 s | +40.88 s |
| USDU only | 87.21 s | +29.25 s |
| Full DETAIL | 193.63 s | +135.67 s |
| Full DETAIL + SageAttention | 176.76 s | -16.87 s vs DETAIL |
| Full Turbo Initial + DETAIL + SageAttention | 195.48 s | rejected |
| All DETAIL Spectrum, run 1 | 121.78 s | anomalous fast run |
| All DETAIL Spectrum, run 2 | 277.53 s | rejected |
| All DETAIL Spectrum, run 3 | 256.75 s | rejected |
| Face + Eye Spectrum; USDU Spectrum off | 178.55 s | stable candidate |

The three isolated feature increments sum to 115.91 seconds. Full DETAIL costs
an additional 19.76 seconds beyond that sum. Logs show repeated Anima, SAM3 and
WanVAE residency changes on the 12 GB card; this interaction/model-swap cost is
the primary optimization target.

## Acceptance gates

1. No optimization may change the effective prompt, seed, resolution, LoRA
   order/strength, or selected checkpoint.
2. Same-seed output must preserve composition and character identity. Minor
   pixel-level differences from an attention backend are acceptable only after
   visual review.
3. A candidate must complete three alternating runs without an error, stall,
   NaN, or missing output.
4. FAST target: mean no slower than 58 seconds; preferred improvement >= 5%.
5. DETAIL target on the reference machine: mean <= 130 seconds. A change that
   saves less than 10 seconds or 8% is not sufficient by itself.
6. Peak VRAM must remain within 12 GB without CPU offload thrashing.
7. I2I first and second generation must both pass after any cache-policy change.

## Optimization order

1. Reorder or share Face/Eye SAM3 detection so SAM3 is loaded once.
2. Reuse the Anima model between Face/Eye detail passes instead of alternating
   Anima, SAM3 and VAE residency.
3. Test whether the Face detailer already provides acceptable eye quality; only
   then consider removing the separate Eye pass.
4. Keep SageAttention as an independent optional acceleration after graph-level
   model-residency work. Its measured DETAIL gain was 8.7%, but it cannot fix
   the model-swap bottleneck.
5. Do not use Full Turbo Initial as the default. The tested 10-step/CFG-1 path
   did not reduce DETAIL time and materially changed same-seed composition.
6. Do not enable Spectrum inside USDU by default. It produced one 121.78-second
   run followed by 277.53- and 256.75-second runs; the repeated slowdown was
   observed in UltimateSDUpscale. Face/Eye Spectrum without USDU Spectrum was
   stable at 178.55 seconds but does not meet the 130-second target alone.
