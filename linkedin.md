# I made every open model on Crusoe sit a West African exam. Here is what happened.

Two million students sit the West African Senior School Certificate Examination every year. It decides who gets into university across Ghana, Nigeria, Sierra Leone, Liberia and The Gambia. So when I wanted to know how open models handle knowledge written for the rest of the world, this was the paper I reached for.

Crusoe Managed Inference serves thirteen open chat models behind one OpenAI-compatible endpoint, so the comparison is clean: same prompt, same key, same afternoon. I gave each model 41 objective questions, mostly Integrated Science from the 2007 paper plus samples in Maths, English and Social Studies, asked for the letter only, and scored against the official key.

**The results**

Ten of the thirteen models got every reviewed question right. GPT-OSS 120B and Qwen3.8 27B missed one. Gemma 4 31B missed two. Nemotron 3 Nano Omni Reasoning 30B was the top scorer against the published key at 39 of 41, with Nemotron 3.5 Lightning 30B next at 38.

So accuracy did not separate them. Price and speed did. The same exam cost a cent and a half per thousand questions on Gemma 4, which answered each one with a single letter and no reasoning, and $2.20 per thousand on Qwen3.8, which thought for about a thousand tokens per question and still missed one. That is a 150 to 1 spread for the same marks.

The best value in the current catalog is GLM-5.3 Flash: full marks, nine cents per thousand questions, a bit over a second per answer. DeepSeek V4.1 Flash matches it on accuracy and is the fastest of the perfect scorers at under a second. The whole run, 533 model answers, cost 23 cents at list price.

**The part I did not expect**

Four questions were missed by nearly every model. When thirteen models that otherwise agree all pick the same "wrong" answer, you check the key. The key was wrong. One soil experiment question divides by the wrong volume; the answer in the dataset is 6.25 percent and the arithmetic gives 14.28. A kettle question gives the working current where it should give the fuse rating. A horticulture question has the propagation method backwards. The models audited the answer key for free, which is a trick worth stealing for any multiple-choice bank you are about to trust.

**What this does and does not say**

The bank is small and old. 41 questions, most of them science from 2007, and the other subjects are three-question samples. The ceiling is low because the current generation of open models is very good at this kind of material and because 2007 questions have had time to leak into training data. Treat the per-subject numbers as a sketch. Treat the cost and latency numbers as the real finding.

**What I need**

Past papers with verified answer keys, especially Core Mathematics, English Language and Social Studies. The question format is a few lines of JSON and the runner picks up new files automatically. The repo has the harness, the raw per-question records, the charts and the full write-up:

https://github.com/acheamponge/wassce-open-models-benchmark

If you have ever sat this exam, or taught for it, I would like to hear which questions you think a model should fail.
