# oot-sw2-save

读写 **《塞尔达传说 时之笛》Nintendo Switch 2 重制版**（2026 年 11 月发售）的存档。
不是 N64 原版，不是 3DS 版，也不是 Ship of Harkinian。

[![tests](https://github.com/ZhaowTao/oot-sw2-save/actions/workflows/tests.yml/badge.svg)](https://github.com/ZhaowTao/oot-sw2-save/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 为什么要做这个

如果你改过这个游戏的存档、进游戏却发现**什么都没变**，原因基本是这个：

> 游戏用的是**六个轮换的 `progress.sav` 槽位**，读档时只加载最新写入的那一个；运行期间它挂载的是事务工作副本 `save.work`，退出时再把内存里的数据整体刷回目录。

只改 `slot_05`、游戏却读了 `slot_02`，等于没改。游戏在跑的时候改 `save/`，会被整份覆盖。两种故障从外面看一模一样：游戏正常启动，你改的那个数字还是老样子。

而且存档的键不是顺序编号，是哈希：

```python
field_id("PlayerStatus.DiveDepth")              # 1632005153
field_id("PouchData.Item_Scale_Gold.StockNum")  # 1256920074
```

也就是 **字段名的 MurmurHash3 x86 32 位哈希，UTF-8，seed 0**。用社区编辑器公开的 1,953 个字段名校验，命中 1,939 个。知道这个之后，字段名就变成了**可以验证的假设**，而不再是需要猜的 32 位数字。

这个项目就建立在上面这两件事上：一条命令改掉**所有槽位 + 工作副本**，并且支持**按名字**读写任意字段。

---

## 安装

只用标准库，没有第三方依赖。

```bash
git clone https://github.com/ZhaowTao/oot-sw2-save
cd oot-sw2-save
python3 -m pip install .
```

或一次性安装：

```bash
pipx install git+https://github.com/ZhaowTao/oot-sw2-save
```

---

## 用法

所有命令既可以指向单个 `*.sav` 文件，也可以指向整个存档目录。指向目录时默认操作**游戏会加载的那个槽位**。

### 看哪个槽位是当前生效的

```console
$ ootsw2 slots "<存档根目录>"
root     /Users/dawn/Library/Application Support/nxnative/0400486024DEC000
work copy present (6 slot(s))

SLOT    WRITTEN                    SIZE  FIELDS  IN save.work  STATUS
slot_00 2026-11-13 02:11:23      169408   11926          same
slot_01 2026-11-13 02:10:11      169344   11926          same
slot_02 2026-11-13 02:13:47      169504   11926          same
slot_03 2026-11-13 02:11:58      169464   11926          same
slot_04 2026-11-13 02:15:39      169440   11926          same  ACTIVE (game loads this)
slot_05 2026-11-13 02:14:27      169416   11926          same
```

`ootsw2 roots` 可以自动找本机的存档目录。

### 按名字读字段

```console
$ ootsw2 get "<存档根目录>" PlayerStatus.DiveDepth PlayerStatus.EquipWeapon PlayerStatus.CurrentRupee
[slot_04 (newest)]
  PlayerStatus.DiveDepth                       9
  PlayerStatus.EquipWeapon                     Weapon_Sword_Master
  PlayerStatus.CurrentRupee                    759
```

字符串字段会从负载区的字符串池自动解出来。`get` / `list` / `diff` 都支持 `--json`。

### 一次改掉所有槽位

```console
$ ootsw2 set "<存档根目录>" PlayerStatus.DiveDepth 9 --type float --all-slots
backup -> .../0400486024DEC000-save-before-edit-20261113_021930
  slot_00                PlayerStatus.DiveDepth: 1091567616 -> 9.0 (float)
  slot_01                PlayerStatus.DiveDepth: 1091567616 -> 9.0 (float)
  ...
  mirrored save/ -> save.work/
```

`--all-slots` 会写全部六个槽位**并**镜像到 `save.work/`，这是唯一能确保游戏看得到改动的做法。默认先备份 `save/`（`--no-backup` 可关闭）。`--dry-run` 只打印计划、不动文件。

### 比较两份存档

```console
$ ootsw2 diff slot_04/progress.sav /tmp/progress-before.sav --named-only
7 field(s) differ
KIND    FIELD                         BEFORE           AFTER
changed PlayerStatus.DiveDepth                6               9
changed PlayerStatus.Life                    44              48
changed PlayerStatus.CurrentRupee           666             759
```

这是解开剩下那些匿名字段的正确办法：**游戏里只做一件事 → 差分两份存档 → 唯一变动的那个字段就是答案**，再用 `probe` 确认名字。

### 试探字段名是否存在

```console
$ ootsw2 probe "<存档根目录>" PlayerStatus.DiveDepth PlayerStatus.SwimSpeed
probing slot_04 (newest) (11926 fields)
  hit    PlayerStatus.DiveDepth                               9  (float)
  miss   PlayerStatus.SwimSpeed

1/2 present
```

`probe` 直接对候选名求哈希再查表，不用打开任何编辑器就能验证一个猜想。有命中返回 0，全没命中返回 2。

### 浏览字典

```console
$ ootsw2 names --prefix PlayerStatus.
PlayerStatus.CurrentRupee
PlayerStatus.DiveDepth
PlayerStatus.EquipArmor
PlayerStatus.EquipBoot
PlayerStatus.EquipHeadArmor
PlayerStatus.EquipOcarina
PlayerStatus.EquipShield
PlayerStatus.EquipWeapon
PlayerStatus.Life
PlayerStatus.MaxLife
...
```

---

## 当库用

```python
from ootsw2 import SaveFile, SaveDirectory

save = SaveFile("slot_04/progress.sav")
print(save.get_float("PlayerStatus.DiveDepth"))   # 9.0
print(save.get_str("PlayerStatus.EquipArmor"))    # 'Armor_Adult_Zora'
save.set_float("PlayerStatus.DiveDepth", 6.0)
save.save()

directory = SaveDirectory("/path/to/0400486024DEC000")
saves = directory.open_all()
for slot in saves.values():
    slot.set_int("PlayerStatus.CurrentRupee", 500)
directory.save_all(saves)          # 写入六槽并镜像 save.work
```

`SaveFile` 保留原始字节，只就地改值字，所以**没碰过的字段与输入逐字节一致**；除非写入更长的字符串，文件长度不变。

---

## 目录结构

| | |
|---|---|
| `ootsw2/container.py` | 容器读写：键值表、负载区、字符串池、就地改写 |
| `ootsw2/hash.py` | MurmurHash3-32 与「字段名 → 键」的推导 |
| `ootsw2/savedir.py` | 六槽轮换、`save.work` 镜像、备份 |
| `ootsw2/fields.py` | 字段字典，带哈希自校验 |
| `ootsw2/cli.py` | 上面的那些命令 |
| `docs/FORMAT.md` | 完整格式文档，含尚未弄清的部分 |

字典含 **1,984 个字段名**，其中 1,970 个满足 `field_id(name) == key`——是自校验的，不是照抄来的。剩下 14 个由 `ootsw2 verify-dict` 列出，全是不满足哈希关系的 `<地牢>.SmallKeyNum` 遗留别名。

---

## 诚实的边界

* **改之前先退出游戏。** 运行中的游戏会在退出时把内存状态刷回目录。
* **大部分字段仍无名字。** `progress.sav` 里约 83% 的字段没有已知名字，而且没法靠暴力枚举解决：用游戏自身字符串表拼出的 920 万种组合里只解出不到 60 个，多数还是巧合。
* **值的类型是推断出来的，文件里没有类型标记。** 数值和负载区偏移靠启发式区分（见 `docs/FORMAT.md` §4.2）。目前对所有有名字段都正确，也可以用 `--type` 强制指定。
* **新增字段支持但未验证。** 表里有空闲槽位，`SaveFile.add()` 能填进去；但只有游戏本来就会写的字段被确认过能生效。
* **没在真机上测过。** 所有结论都是「改存档 → 在运行中的游戏里看到变化」验证的，但那次运行是走原生重编译层的 macOS 宿主，不是 Switch 2 本体。容器格式是游戏自己的，理论上通用；路径和 `save.work` 行为属宿主侧。
* **本仓库不包含任何游戏代码、游戏资源或存档文件**，与任天堂无关。请只改自己的存档、留好备份。

MIT 协议，见 [LICENSE](LICENSE)。英文说明见 [README.md](README.md)。
