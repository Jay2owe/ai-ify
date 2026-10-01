<!-- aiify app map: app=aiify-demo sources=56cb28b40d991696 built=2026-10-01 by=claude -->
# App map: aiify-demo

## Overview
aiify-demo is a small web page for keeping a table of mouse samples. Each sample has an id, a name, a genotype and an "included" flag (yes or no). The page can show the samples as a table or as a summary that counts the included samples by genotype. Researchers use it to track which samples count towards the summary. A built-in assistant panel can also do these jobs when asked in plain language.

## Screens
### Samples page (table view)
Opens at `/`. This is the default view, and the page is titled "Samples". It lists every sample as a row with the columns id, name, genotype and included (yes or no). Click a row to outline it as the selected sample. A row briefly highlights yellow when it changes. The page refreshes itself every second or so. The top bar has these controls:
- **View**: a drop-down with "table" and "summary".
- **Include all**: marks every sample as included.
- **Reset**: restores the starting data.
- **Explain the summary**: asks the assistant for a short explanation of the summary.

### Summary view
Choose "summary" in the **View** drop-down. It shows one line, "Included samples by genotype:", followed by a count for each genotype, for example "APP 1, WT 1". It shows "none" if no sample is included. Excluded samples are not counted. The top bar is the same as in the table view.

### Danger zone
A dashed red box at the bottom of the page. It holds the **Delete everything** button, which removes all samples. The box is marked as off-limits to the assistant, so the assistant does not use it.

### Assistant panel
A chat panel added to the page. You type requests in plain language. It offers suggested prompts: "Which samples are excluded?" and "Add sample M04 with genotype APP". It supports queuing messages while it is answering, scheduling a message for a later time ("Later"), attachments and notes. It has two profiles. "Assistant" can look at and change data. "Look only" can only read the summary and change what is shown.

## Tasks
### How to see the table of samples
1. Open the page at `/`.
2. In **View**, choose "table", or use the assistant action `show_view` with view "table".

### How to see the summary of included samples by genotype
1. In **View**, choose "summary".
2. Read the line "Included samples by genotype".
3. Or run `samples.summary`, which returns the counts by genotype.

### How to switch between table and summary
1. Use the **View** drop-down and pick "table" or "summary".

### How to add a sample
1. Run `samples.add` with a name and a genotype, for example name M04, genotype APP. The page has no add form, so this goes through the assistant.
2. Or ask the assistant, for example "Add sample M04 with genotype APP".
3. The new sample is included by default and appears as a new row in the table view.

### How to exclude a sample from the summary
1. Find the sample's id in the table view.
2. Run `samples.include` with that sample id and included set to false.
3. The table's included column shows "no" and the summary no longer counts it.

### How to include a sample again
1. Find the sample's id in the table.
2. Run `samples.include` with that sample id and included set to true.

### How to include all samples at once
1. Click **Include all**.
2. Or run the route `route.include_all` (POST /api/include_all).

### How to delete one sample
1. Find the sample's id in the table.
2. Run `samples.remove` with that id. This deletes the sample, so confirm first.

### How to find out which samples are excluded
1. Open the table view.
2. Look for rows where the included column says "no".
3. Or use the suggested prompt "Which samples are excluded?".

### How to select (outline) a sample row
1. In the table view, click the row.
2. Or use the assistant action `select_sample` with the sample's id. It switches to the table view and outlines the row.

### How to get the current list of samples
1. Run `route.state` (GET /api/state). It returns the samples and change counters.

### How to reset the data to the starting samples
1. Click **Reset**.
2. Or run `route.reset` (POST /api/reset).
3. This restores the three starting samples (M01 WT, M02 APP, M03 APP excluded) and returns the page to the table view.

### How to delete all samples
1. Click **Delete everything** in the Danger zone.
2. Or run `route.wipe` (POST /api/wipe).
3. Use **Reset** afterwards to get the starting samples back.

### How to get an explanation of the summary
1. Click **Explain the summary**.
2. The assistant switches to the summary view and explains it in two sentences, using the "Look only" profile.

### How to ask the assistant for help
1. Open the assistant panel.
2. Type a request, or pick a suggested prompt.
3. Optionally attach files or add notes.

### How to queue a message while the assistant is answering
1. While the assistant is answering, type your next message.
2. Press Tab to queue it.

### How to schedule a message for later
1. In the assistant panel, use **Later** to pick a time for the message to be sent.

### How to restrict the assistant to looking only
1. In the assistant panel, choose the "Look only" profile.
2. This profile can only run `samples.summary` and change what is shown. It will not change data.

### How to get a genotyping cost estimate
1. Ask the assistant a question that mentions "cost" or "price".
2. It adds the price note: genotyping costs 12 pounds per sample, multiplied by the number of samples in the table.

## Terms
### Sample
One row in the table: an id, a name (such as M01), a genotype and an included flag.

### Genotype
The mouse's genetic type, such as WT or APP. The summary counts samples by it.

### Included
Whether a sample counts towards the summary. New samples are included by default. Shown as "yes" or "no" in the table.

### Table view
The default view, listing every sample as a row.

### Summary view
The view that counts included samples by genotype.

### Danger zone
The box holding **Delete everything**. The assistant is blocked from using it.

### Profile
A mode for the assistant. "Assistant" can read and change data. "Look only" can only read the summary and change what is shown.

### Launch button
A page button that starts the assistant with its own built-in instructions. **Explain the summary** is the one here.

### Suggested prompts
Ready-made questions shown in the assistant panel.

### Selected sample
The row you clicked, or chose through `select_sample`. It is outlined in blue.
