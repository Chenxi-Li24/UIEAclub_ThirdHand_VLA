# Login visual revision — 2026-10-30

Status: warm orange revision approved by the user on 2026-10-30 ("通过。git远端已更新"). UI implementation may follow this direction under the approved execution plan. Deployment remains a separate acceptance step.

The user's current workspace uses white, vivid orange (#F37324 / #F27A2A), charcoal (#26313B), gray (#6F7A84), and subtle dividers (#E9ECEF). The login should share that family while using its own related shades. The revised board retains three screens: Observer sign-in selected by default, Administrator permission notice, and registration without role selection.

Proposed surface tokens: warm white `#FFFCF9`, translucent near-white glass, apricot accent `#ED823D`, readable dark orange links `#AE4E18`, peach tint `#FFF0E4`, charcoal `#2B3540`, muted text `#727C85`, warm gray border `#E8E9E7`. Button gradients must be adjusted in implementation to meet text contrast; the drawing is visual direction, not a pixel-exact accessibility guarantee. Error colors stay distinct from brand orange. Status indicators retain their semantic meaning in the workspace.

English remains the first-visit default, with EN / 中文 and a shared theme switch. Observer is selected on every new login. Existing approved role and session semantics remain unchanged. Screenshots and final CSS values will be recorded after approval and browser verification.
