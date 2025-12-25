# DailySelfie Material 3 Theming Guide

## 🐍 How to Use in Code

**Do not hardcode colors.** Always access them through the `theme_vars` proxy.

```python
from gui.theme.theme_vars import theme_vars

# 1. Get the global theme instance
v = theme_vars()

# 2. Use a color (returns Hex String)
style = f"background-color: {v['surface_container']};"

# 3. Get a QColor object (for Painters)
painter.setBrush(v.qcolor("primary"))

# 🎨 1. Surfaces & Backgrounds

These form the foundation of your app layout.

| Key                     | Usage                                                               | Hex (Dark Ref) |
| :---------------------- | :------------------------------------------------------------------ | :------------- |
| `background`            | App Root. The absolute lowest layer. Use for the main window background. | `#1C1B1F`      |
| `surface`               | Standard Surface. Main background for pages.                        | `#1C1B1F`      |
| `surface_container_low` | Cards / List Items. Use for widgets sitting on the background.      | `#1F1E23`      |
| `surface_container`     | Sidebars / Panels. Good for navigation rails or bottom sheets.      | `#232128`      |
| `surface_container_high`| Modals. Use for dialogs or floating popups.                         | `#28262E`      |
| `surface_container_highest`| Active States. Use for selected items or highlighted rows.          | `#2E2C34`      |

✍️ 2. Text & Content

Always pair text colors with their correct background to ensure readability.

| On Background... | Use Text Color... | Example Context                           |
| :--------------- | :---------------- | :---------------------------------------- |
| `surface`        | `on_surface`      | Main headings, paragraphs.                |
| `surface`        | `on_surface_variant`| Subtitles, help text, timestamps.         |
| `primary`        | `on_primary`      | Text inside a filled Primary button.      |
| `secondary`      | `on_secondary`    | Text inside a filled Secondary button.    |
| `tertiary`       | `on_tertiary`     | Text inside a Tertiary accent chip.       |
| `error`          | `on_error`        | Text inside an error message box.         |

🚀 3. Buttons & Actions

**Primary Action** (e.g., "Capture", "Save")

*   Background: `primary`
*   Text/Icon: `on_primary`
*   Hover: `primary_fixed_dim` (optional preference) or lighten primary.

**Secondary Action** (e.g., "Retake", "Cancel")

*   Background: `secondary`
*   Text/Icon: `on_secondary`

**Tonal Action** (e.g., "Mute", "Settings")

*   Background: `secondary_container`
*   Text/Icon: `on_secondary_container`

**Ghost / Text-Only Button**

*   Background: Transparent
*   Text: `primary`
*   Hover Bg: `surface_container_highest` (low opacity)

🔲 4. Borders & Outlines

| Key             | Usage                                                      |
| :-------------- | :--------------------------------------------------------- |
| `outline`       | Focus / Active. Use for text input borders when focused.   |
| `outline_variant`| Divider / Inactive. Use for list separators or inactive input borders. |

⚠️ 5. Status & Errors

| Key                | Usage                                                      |
| :----------------- | :--------------------------------------------------------- |
| `error`            | High Priority. Background for delete buttons.              |
| `on_error`         | Text on top of error.                                      |
| `error_container`  | Low Priority. Background for validation warning banners.   |
| `on_error_container`| Text inside validation banners.                            |

🌈 6. Special Colors

| Key                | Usage                                                      |
| :----------------- | :--------------------------------------------------------- |
| `inverse_surface`  | Tooltips / Toasts. Dark background on light theme (and vice versa). |
| `inverse_on_surface`| Text inside tooltips/toasts.                               |
| `scrim`            | Overlay. Semi-transparent black to dim background behind modals. |
| `shadow`           | Drop shadow color.                                         |