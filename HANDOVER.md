# 准光子CT 2048×2048 全身血管铸型数据分析项目 — 交接文档

> **日期**: 2025-07-23  
> **数据**: 全球首例准光子CT 2048×2048矩阵重建，19岁男性全身血管铸型  
> **扫描参数**: 120 kVp, 螺旋模式, 0.156 mm 层厚, 0.244×0.244 mm 面内  
> **扫描覆盖**: Z=484–2,418 mm (1,934 mm), 12,398 层

---

## 1. 项目概述

对全球首例准光子探测器CT 2048×2048矩阵重建的19岁男性全身血管铸型数据集进行了系统性分析，涵盖体积组装、血管分割、形态计量、对称性分析、分辨率表征、三维体渲染和系统组学分析。

### 1.1 核心成果

| 交付物 | 文件 | 大小 |
|--------|------|------|
| **HTML 学术报告** | `vascular_research_report.html` | ~51 MB |
| **Word 草稿** | `准光子CT_全身血管铸型_中华放射学.docx` | ~37 MB |
| **DICOM 数据** | `01_Skull_Vault/` ~ `13_Foot_Ankle_Distal/` | ~50 GB |

### 1.2 关键定量发现

| 指标 | 值 |
|------|-----|
| 中位血管直径 | 1.48 mm |
| 最小可检测血管 | 0.275 mm |
| MTF10% 等效分辨率 | 0.136 mm |
| 亚毫米血管（全身上腹区） | 8,381 个 (2048²) → 0 个 (512²) |
| 峰值血管密度 | 上腹部 16.7% |
| 解剖区域数 | 11 个（修正后） |

---

## 2. 目录结构

```
good/
├── 01_Skull_Vault/          # Z=484–640mm, 1000 DICOMs
├── 02_Skull_Base_Neck/      # Z=640–796mm, 1000 DICOMs
├── 03_Upper_Limbs_Thorax/   # Z=796–952mm, 1000 DICOMs
├── 04_Upper_Abdomen/        # Z=952–1107mm, 1000 DICOMs
├── 05_Abdomen/              # Z=1108–1264mm, 1000 DICOMs
├── 06_Pelvis/               # Z=1264–1420mm, 1000 DICOMs
├── 07_Upper_Femur/          # Z=1420–1576mm, 1000 DICOMs
├── 08_Lower_Femur/          # Z=1576–1732mm, 1000 DICOMs
├── 09_Knee_Tibial_Plateau/  # Z=1732–1888mm, 1000 DICOMs
├── 10_Mid_Tibia/            # Z=1888–2044mm, 1000 DICOMs
├── 11_Foot_Ankle_Proximal/  # Z=2044–2200mm, 1000 DICOMs
├── 12_Foot_Ankle_Mid/       # Z=2200–2356mm, 1000 DICOMs
├── 13_Foot_Ankle_Distal/    # Z=2356–2418mm, 398 DICOMs
│
├── vascular_research_report.html    # 主报告（中英文混合，22张嵌入式图片）
├── 准光子CT_全身血管铸型_中华放射学.docx  # Word草稿
│
├── vessel_density_profile.png        # 图1
├── vascular_atlas_axial.png          # 图2
├── vascular_mip_projections.png      # 图3
├── diameter_distribution.png         # 图6
├── vascular_density_analysis.png     # 图7
├── resolution_and_summary.png        # 图8
├── omics_profile.png                 # 图22
├── vr_stab_*_*.png                   # 图10-20（11张区域VR）
├── vr_multires_*.png                 # 多分辨率对比
├── vr_resolution_comparison.png      # 图21
├── wholebody.png, heart.png          # 用户提供的3D渲染
├── 血管（去骨）.png                   # 去骨血管渲染
│
├── vessel_density_profile.npz        # Z轴密度数据
├── vessel_diameters.npz              # 血管直径数据
├── mtf_data.npz                      # MTF/ESF/LSF数据
├── vascular_omics.json               # 组学形态计量数据
├── multires_vessel_counts.json       # 多分辨率血管计数
│
└── SSD+VR_github/                    # VR渲染器源码（副本）
```

---

## 3. 环境配置

### 3.1 Python 环境

| 环境 | Python | 路径 | 用途 |
|------|--------|------|------|
| **base (python)** | 3.x | `D:\python\` | pydicom, numpy, scipy, matplotlib, PIL, python-docx |
| **mar** | 3.11 | `D:\python\envs\mar\` | VTK 9.6.1, SimpleITK 2.3.1, PySide6, PyCt6 |

### 3.2 关键 Python 包

```
# base 环境
pip install pydicom numpy scipy matplotlib pillow python-docx scikit-image openpyxl

# mar 环境
D:\python\envs\mar\python.exe -m pip install vtk SimpleITK pydicom numpy scipy pillow
```

### 3.3 VR 渲染器

- **路径**: `I:\SSD+VR_github\ssd_vr_viewer.py` (3,680行)
- **启动**: `D:\python\envs\mar\python.exe I:\SSD+VR_github\ssd_vr_viewer.py --input <DICOM目录>`
- **模式**: stable, cinematic, hd_surface, nature_channels, frangi, 等12种
- **说明**: `pv_packages` 目录缺失不影响运行（mar 环境自带 PySide6）

---

## 4. 关键技术要点

### 4.1 解剖标注修正（最重要的发现）

**原始标注与真实 HFS 体位系统性倒置**。修正后:

```
低 Z (484mm) = 头端（颅顶骨）
高 Z (2418mm) = 足端（足踝关节）
```

之前密度峰值被错误归因于"膝部"→ 修正为"上腹部"（腹腔干/SMA 供血，16.7%）。

### 4.2 字典序排序陷阱

`ImageResult1000` 在 Python 默认字符串排序下置于 `ImageResult100` 和 `ImageResult101` 之间。
**所有 DICOM 索引必须使用数值排序**:

```python
def nsort(fname):
    m = re.search(r'ImageResult(\d+)', fname)
    return int(m.group(1)) if m else 0
```

### 4.3 SimpleITK 多文件夹混合问题

**禁止**将不同 DICOM 系列的 InstanceNumber 重叠文件复制到同一临时目录。
SimpleITK 的 `GetGDCMSeriesFileNames()` 会将它们错误识别为同一系列，导致 Z 间距异常（曾出现 1401mm 错误值）。

**正确做法**: pydicom 按 `SliceLocation` 显式排序后直接构建 numpy 数组。

### 4.4 vtkPNGWriter 故障

mar 环境中的 `vtkPNGWriter` 无法正常工作（`libpng write error`）。
**解决方案**: 使用 `vtkWindowToImageFilter` → `vtk_to_numpy` → PIL `Image.fromarray().save()`

### 4.5 体渲染管线（SSD+VR 双层融合）

正确的渲染参数对齐 viewer 默认 Stable 模式:

```python
# SSD 层（骨骼外壳）
opacity: [(-1000,0),(320,0),(420,0.01),(560,0.10),(760,0.52),(980,0.86),(1300,1.0)]
color:   [(-1000,0,0,0),(420,0.80,0.78,0.75),(760,0.95,0.93,0.90),(1300,1,1,1)]

# VR 层（Cinematic 血管增强）
opacity: [(-1000,0),(-950,0),(-900,0.12),(-400,0.20),(-350,0),(100,0),(150,0.60),(250,0.90),(550,0.95),(600,0)]
color:   [(-1000,0,0,0),(-950,0.29,0,0.51),(-400,0.15,0,0.35),(150,1,0.55,0),(550,1,0.96,0)]

# 光照
ambient=0.1, diffuse=0.9, specular=0.2, specularPower=10
background=(0.02,0.02,0.05)

# 预处理
int16 VTK_SHORT + Gaussian 3D σ=0.4
```

### 4.6 HTML 图片嵌入陷阱

字符串替换（如正则表达式 `re.sub`）在处理大型 base64 数据时可能引入损坏。
**正确做法**: 从零用 `f.write()` 构建 HTML，不依赖运行时替换。alt 标签匹配是最可靠的更新方法。

---

## 5. 已完成的 12 个分析章节

| 章节 | 内容 | 图表 |
|------|------|------|
| 1 | 摘要 | - |
| 2 | 引言 | - |
| 3 | 数据特征 | 表1 |
| 4 | 方法 | - |
| 5.1 | 体积组装 | 表1（修正）, 图1-3 |
| 5.2 | 血管图谱 | 图2-5 |
| 5.3 | 直径分布 | 图6 |
| 5.4 | 密度与对称性 | 图7 |
| 5.5 | 分辨率极限 | 图8, 表2 |
| 5.6 | 去骨血管 | 图9 |
| 6 | 讨论 | 表3（平台对比） |
| 7 | 结论 | - |
| 8 | 技术说明 | 文件夹重命名记录 |
| 9 | 超高分辨率CT技术综述 | 表3 |
| 10 | 区域VR图谱 | 图10-20（11张Cinematic VR） |
| 11 | 三维多分辨率分析 | 图21, 表6 |
| 12 | 三维血管组学 | 图22, 表7 |

---

## 6. 已知限制与待办

| 项目 | 状态 | 说明 |
|------|------|------|
| 图像中文化 | ✅ 完成 | 图1-3,6-8,22 均已替换为中文 |
| HTML 全文翻译 | ✅ 完成 | Sections 1-12 + 图注/表注 |
| 文件夹重命名 | ✅ 完成 | 13个文件夹按Z轴顺序命名 |
| Word 文档更新 | ⚠️ 部分 | 旧文件夹名残留，需重建 |
| Section 10 图注中文化 | ⚠️ 待处理 | VR区域图谱图注仍含英文 |
| 多受试者验证 | ❌ 未开始 | 单标本研究的根本局限 |
| 组织学对照 | ❌ 未开始 | 微血管可视化极限的外部验证 |

---

## 7. 常用命令速查

```bash
# DICOM 标签读取
python -c "import pydicom; ds=pydicom.dcmread('文件路径', stop_before_pixels=True); print(ds)"

# 单区域 VR 渲染 (1024², Cinematic TF)
"D:/python/envs/mar/python.exe" -c "
import pydicom, os, re, numpy as np, vtk ...
# 加载 Z 范围切片 → int16 → Gaussian σ=0.4 → VTK_SHORT → SSD+VR 融合 → 截图
"

# HTML 图片更新 (alt 标签精准替换)
python -c "
import base64, re
h = open('report.html').read()
# 找到 'alt=\"density\"' 定位图片, 用新 base64 替换

# 组学分析
python omics_3d.py  # 生成 vascular_omics.json

# 报告重建
python build_html.py  # 从零构建 HTML（推荐用于大规模修改）
```

---

## 8. 关键文件映射

| 文件名 | 用途 | 生成方式 |
|--------|------|---------|
| `vessel_density_profile.npz` | 密度剖面数据 | `rebuild_density.py` |
| `vessel_diameters.npz` | 血管直径原始数据 | `vessel_morphometry.py` |
| `mtf_data.npz` | MTF/ESF/LSF 数组 | `mtf_analysis.py` |
| `vascular_omics.json` | 组学形态计量结果 | `omics_3d.py` |
| `multires_vessel_counts.json` | 多分辨率血管计数 | `vessel_count_multires.py` |
