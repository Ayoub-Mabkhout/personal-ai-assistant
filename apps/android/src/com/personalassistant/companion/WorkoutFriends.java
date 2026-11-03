package com.personalassistant.companion;

import android.widget.LinearLayout;
import org.json.JSONArray;
import org.json.JSONObject;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;

/** Shared Train standings and the read-only view of another athlete. */
final class WorkoutFriends {
    private static final String PATH = "workout/friends";
    private static final DateTimeFormatter SESSION = DateTimeFormatter.ofPattern("EEE d MMM, HH:mm xxx");
    private final WorkoutScreen screen;
    private final AppUi ui;

    WorkoutFriends(WorkoutScreen screen) {
        this.screen = screen;
        this.ui = screen.ui;
    }

    void open() {
        WorkoutViews.Sheet sheet = new WorkoutViews.Sheet(ui, "Friends");
        sheet.body.addView(ui.detail("Loading standings…"));
        sheet.show();
        new Thread(() -> {
            try {
                JSONObject standings = (JSONObject) Cloud.call(screen.a, PATH, null, true);
                JSONObject preferences = (JSONObject) Cloud.call(screen.a, PATH + "/me", null, true);
                screen.a.runOnUiThread(() -> showStandings(sheet, standings.optJSONArray("items"), preferences));
            } catch (Exception error) {
                unavailable(sheet, "Connect to Train to see your friends.");
            }
        }).start();
    }

    private void showStandings(WorkoutViews.Sheet sheet, JSONArray items, JSONObject preferences) {
        sheet.body.removeAllViews();
        boolean enabled = preferences.optBoolean("rank_alerts");
        sheet.body.addView(ui.quietButton(enabled ? "Competitive notifications on" : "Turn on competitive notifications",
                () -> changeAlerts(sheet, items, !enabled)), WorkoutViews.gap(ui, 10));
        if (items == null || items.length() == 0) {
            sheet.body.addView(ui.detail("No members on the standings yet."));
            return;
        }
        java.util.ArrayList<JSONObject> ranked = new java.util.ArrayList<>();
        for (int i = 0; i < items.length(); i++) ranked.add(items.optJSONObject(i));
        ranked.sort((left, right) -> Integer.compare(right.optInt("lifting_score", -1), left.optInt("lifting_score", -1)));
        for (JSONObject member : ranked) {
            JSONObject sprint = member.optJSONObject("current_sprint");
            String subtitle = tier(member, "lifting_score");
            if (sprint != null) subtitle += " · " + sprintProgress(sprint);
            sheet.body.addView(WorkoutViews.row(ui, member.optString("name"), subtitle,
                    () -> profile(member.optString("id"), false)), WorkoutViews.gap(ui, 6));
        }
    }

    private void changeAlerts(WorkoutViews.Sheet sheet, JSONArray items, boolean enabled) {
        new Thread(() -> {
            try {
                JSONObject changed = (JSONObject) Cloud.call(screen.a, PATH + "/me",
                        new JSONObject().put("rank_alerts", enabled), true);
                screen.a.runOnUiThread(() -> showStandings(sheet, items, changed));
            } catch (Exception error) {
                screen.a.runOnUiThread(() -> android.widget.Toast.makeText(screen.a,
                        "Couldn't save notification settings.", android.widget.Toast.LENGTH_SHORT).show());
            }
        }).start();
    }

    void profile(String identifier, boolean ranks) {
        if (!identifier.matches("owner|[a-f0-9]{32}")) return;
        WorkoutViews.Sheet sheet = new WorkoutViews.Sheet(ui, "Friend profile");
        sheet.body.addView(ui.detail("Loading profile…"));
        sheet.show();
        new Thread(() -> {
            try {
                JSONObject data = (JSONObject) Cloud.call(screen.a, PATH + "/" + identifier, null, true);
                screen.a.runOnUiThread(() -> showProfile(sheet, data, ranks));
            } catch (Cloud.HttpError error) {
                unavailable(sheet, error.status == 404 ? "This athlete keeps their progress private." : "Connect to Train to see this profile.");
            } catch (Exception error) {
                unavailable(sheet, "Connect to Train to see this profile.");
            }
        }).start();
    }

    private void showProfile(WorkoutViews.Sheet sheet, JSONObject data, boolean ranks) {
        sheet.body.removeAllViews();
        sheet.body.addView(ui.type(data.optString("name"), 24, 30, 750, 0, ui.text), WorkoutViews.gap(ui, 8));
        LinearLayout tabs = ui.row();
        tabs.addView(ranks ? ui.quietButton("Sprint", () -> showProfile(sheet, data, false))
                : ui.primaryButton("Sprint", () -> {}), new LinearLayout.LayoutParams(0, -2, 1));
        tabs.addView(ranks ? ui.primaryButton("Ranks", () -> {})
                : ui.quietButton("Ranks", () -> showProfile(sheet, data, true)), new LinearLayout.LayoutParams(0, -2, 1));
        sheet.body.addView(tabs, WorkoutViews.gap(ui, 12));
        if (ranks) showRanks(sheet, data.optJSONObject("ranks"));
        else showSprint(sheet, data);
    }

    private void showSprint(WorkoutViews.Sheet sheet, JSONObject data) {
        JSONObject sprint = data.optJSONObject("current_sprint");
        if (sprint == null) {
            sheet.body.addView(ui.detail("No active sprint."));
            return;
        }
        LinearLayout summary = WorkoutViews.card(ui);
        summary.addView(ui.type(sprint.optString("name"), 20, 26, 750, 0, ui.text));
        summary.addView(ui.detail(sprintProgress(sprint)));
        sheet.body.addView(summary, WorkoutViews.gap(ui, 12));
        JSONArray schedule = data.optJSONArray("schedule");
        for (int i = 0; schedule != null && i < schedule.length(); i++) {
            JSONObject slot = schedule.optJSONObject(i);
            String status = slot.optString("status");
            String label = status.equals("completed") ? "✓ Completed" : status.equals("missed") ? "× Missed" :
                    status.equals("active") ? "In progress" : status.equals("skipped") ? "Skipped" : "Upcoming";
            int color = status.equals("completed") ? ui.success : status.equals("missed") ? ui.danger : ui.muted;
            LinearLayout row = WorkoutViews.card(ui);
            row.addView(WorkoutViews.pair(ui, slot.optString("name"), label, color));
            row.addView(ui.detail(OffsetDateTime.parse(slot.optString("starts_at")).format(SESSION)));
            sheet.body.addView(row, WorkoutViews.gap(ui, 6));
        }
    }

    private void showRanks(WorkoutViews.Sheet sheet, JSONObject ranks) {
        if (ranks == null) return;
        LinearLayout card = WorkoutViews.card(ui);
        card.addView(WorkoutViews.pair(ui, "Lifting", tier(ranks, "lifting_score"), ui.text));
        JSONObject running = ranks.optJSONObject("running");
        card.addView(WorkoutViews.pair(ui, "Running", running == null ? "Unranked" : running.optString("tier", "Unranked"), ui.text));
        JSONArray lifts = ranks.optJSONArray("lifts");
        for (int i = 0; lifts != null && i < lifts.length(); i++) {
            JSONObject lift = lifts.optJSONObject(i);
            card.addView(WorkoutViews.pair(ui, lift.optString("exercise_name"), lift.optString("tier", "Unranked"), ui.text));
        }
        sheet.body.addView(card);
    }

    private static String tier(JSONObject data, String key) {
        return data.isNull(key) ? "Unranked" : WorkoutViews.label(data.optInt(key));
    }

    private static String sprintProgress(JSONObject sprint) {
        int target = sprint.optInt("target_sessions");
        return sprint.optInt("completed") + (target > 0 ? " of " + target : "") + " sessions completed";
    }

    private void unavailable(WorkoutViews.Sheet sheet, String message) {
        screen.a.runOnUiThread(() -> {
            sheet.body.removeAllViews();
            sheet.body.addView(ui.detail(message));
        });
    }
}
