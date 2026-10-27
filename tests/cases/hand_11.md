---
id: hand_11
source: handwritten
category: CUT&Tag
title: CUT&Tag声称全局下降却用深度归一化
answer: R01, R02, R12
tolerated: R03, R04, R08
---

## Text

CUT&Tag for H3K27me3 was performed in control and GENE-D knockdown cells (one replicate each). Reads were normalized to sequencing depth (CPM). H3K27me3 signal was globally reduced across the genome in knockdown cells, indicating that GENE-D is required for Polycomb-mediated silencing.

## Notes

- Original answer (handwritten): 每组只有一个重复，无法评估重现性；没有IgG阴性对照；声称全基因组整体下降却用CPM深度归一化，这种归一化会抹平全局变化，需要spike-in归一化；抗体特异性未验证；结论过度延伸到Polycomb机制
- 映射：没有IgG阴性对照→R01；每组只有一个重复→R02；声称全局下降却用CPM归一化（需spike-in）、抗体特异性未验证→R12。未映射：结论过度延伸到Polycomb机制。
