# Wind 配置说明

## 是否必须配置 Wind

不是必须。

本工具默认可以使用公开行情和新闻源运行基础 workflow。Wind 只建议作为增强或兜底数据源，例如公开 K 线接口不稳定、需要更可靠的公告/新闻/行情数据时再使用。

## 额度归属

谁的 `WIND_API_KEY` 配置在运行环境里，就消耗谁的额度。

不要把自己的 Key 发给别人，也不要把 Key 写进 GitHub、zip 包、Excel 模板或截图里。

## 获取 Key

访问 Wind AIFin Market 开发者中心：

```text
https://aifinmarket.wind.com.cn/#/user/overview
```

登录后复制自己的 `WIND_API_KEY`。

## Mac 配置方式

打开终端，运行：

```bash
mkdir -p ~/.wind-aifinmarket
printf 'WIND_API_KEY=你的真实Key\n' > ~/.wind-aifinmarket/config
chmod 600 ~/.wind-aifinmarket/config
```

把 `你的真实Key` 替换成自己的 Key。

## Windows 配置方式

在文件资源管理器地址栏输入：

```text
%USERPROFILE%
```

新建文件夹：

```text
.wind-aifinmarket
```

在这个文件夹里新建文件：

```text
config
```

文件内容写：

```text
WIND_API_KEY=你的真实Key
```

保存即可。

## 配置后如何判断是否可用

如果后续工具接入 Wind 兜底，页面会显示 Wind 数据源是否启用、是否成功取数。

当前版本默认不主动消耗 Wind 额度。除非工具页面或脚本明确开启 Wind 兜底，否则不会使用 Wind。

## 建议

- 日常测试优先使用默认公开数据源。
- 公开数据源失败或需要更高质量数据时，再启用 Wind。
- 每个同事配置自己的 Key，不要共用你的 Key。
