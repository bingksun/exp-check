---
id: hand_12
source: handwritten
category: RNA-seq
title: RNA-seq用未校正p值，用同一批样本"验证"
answer: R02, R03
tolerated: R04
---

## Text

RNA-seq was performed on control and treated cells (n = 2 per group). Genes with p < 0.05 (DESeq2 Wald test) were considered differentially expressed, yielding 1,842 DEGs. Three DEGs were validated by qPCR in the same RNA samples used for sequencing.

## Notes

- Original answer (handwritten): 用未校正的p值而非FDR校正后的padj，1842个DEG里大量假阳性；n=2偏少；qPCR验证用的是测序的同一批RNA，不是独立样本，只能算技术确认；批次设计未说明
- 映射：用未校正p值而非FDR→R03（多重比较校正）；n=2偏少、qPCR验证用同一批RNA不是独立样本→R02。未映射：批次设计未说明。
