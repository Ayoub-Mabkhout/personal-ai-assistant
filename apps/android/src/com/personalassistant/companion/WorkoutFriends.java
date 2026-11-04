package com.personalassistant.companion;

import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;

/** Shared Train standings as a league of athletes, and a friend's read-only athlete profile with a head-to-head against you. */
final class WorkoutFriends {
    private static final String PATH = "workout/friends";
    private static final DateTimeFormatter SESSION = DateTimeFormatter.ofPattern("EEE d MMM, HH:mm xxx");
    private static final int VERSUS = 0, SPRINT = 1, RANKS = 2;
    private static final String[] TABS = {"Head-to-head", "Sprint", "Ranks"};
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

    /** Friends as a league: a podium, where you stand and who's next to pass, then everyone's athlete card. */
    private void showStandings(WorkoutViews.Sheet sheet, JSONArray items, JSONObject preferences) {
        if (!sheet.dialog.isShowing()) return;
        sheet.body.removeAllViews();
        sheet.body.addView(alerts(sheet, items, preferences), WorkoutViews.gap(ui, 14));
        if (items == null || items.length() == 0) {
            sheet.body.addView(ui.detail("No members on the standings yet."));
            return;
        }
        String me = preferences.optString("id", "owner");
        ArrayList<JSONObject> order = new ArrayList<>();
        for (int i = 0; i < items.length(); i++) if (items.optJSONObject(i) != null) order.add(items.optJSONObject(i));
        order.sort((left, right) -> Integer.compare(right.optInt("lifting_score", -1), left.optInt("lifting_score", -1)));
        int at = -1, ranked = 0;
        for (int i = 0; i < order.size(); i++) {
            if (me.equals(order.get(i).optString("id"))) at = i;
            if (WorkoutFriendViews.score(order.get(i), "lifting_score") != null) ranked++;
        }
        JSONObject you = at < 0 ? null : order.get(at);
        WorkoutFriendViews.Pick go = member -> open(member, me);
        if (ranked >= 2) sheet.body.addView(WorkoutFriendViews.podium(ui, order.subList(0, Math.min(3, order.size())), me, go), WorkoutViews.gap(ui, 16));
        if (you != null) sheet.body.addView(WorkoutFriendViews.standing(ui, order, at), WorkoutViews.gap(ui, 16));
        sheet.body.addView(ui.label("The league"), WorkoutViews.gap(ui, 8));
        for (int i = 0; i < order.size(); i++) sheet.body.addView(WorkoutFriendViews.athlete(ui, order.get(i), i, you, me, go), WorkoutViews.gap(ui, 8));
        sheet.body.addView(ui.type("Ordered by overall lifting rank. Friends who share their progress open to their profile.", 12, 17, 400, 0, ui.muted), MainParts.params(ui, -1, -2, 0, 4, 0, 0));
    }

    /** Yourself opens your own Ranks; a friend who shares opens their profile; a private member only says so. */
    private void open(JSONObject member, String me) {
        if (me.equals(member.optString("id"))) screen.ranks();
        else if (member.optBoolean("share_progress")) profile(member.optString("id"), false);
        else Toast.makeText(screen.a, member.optString("name", "This athlete") + " keeps their progress private", Toast.LENGTH_SHORT).show();
    }

    /** Compact switch for competitive notifications; a failed save puts the switch back. */
    private View alerts(WorkoutViews.Sheet sheet, JSONArray items, JSONObject preferences) {
        boolean enabled = preferences.optBoolean("rank_alerts");
        LinearLayout row = ui.row();
        row.setTag("friends_alerts");
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setMinimumHeight(ui.dp(52));
        row.setPadding(ui.dp(14), ui.dp(2), ui.dp(6), ui.dp(2));
        row.setBackground(ui.outline(ui.surface, 16, ui.stroke, 1));
        TextView title = ui.type("Competitive notifications", 14, 19, 600, 0, ui.text);
        title.setSingleLine(true);
        title.setEllipsize(android.text.TextUtils.TruncateAt.END);
        row.addView(title, MainParts.weighted(ui, 1, 0, 0, 8, 0));
        Switch control = ui.switchControl(enabled, "Competitive notifications");
        row.addView(control, new LinearLayout.LayoutParams(ui.dp(56), ui.dp(48)));
        row.setOnClickListener(v -> control.performClick());
        row.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        control.setOnCheckedChangeListener((button, checked) -> {
            control.setEnabled(false);
            changeAlerts(sheet, items, preferences, checked);
        });
        return row;
    }

    private void changeAlerts(WorkoutViews.Sheet sheet, JSONArray items, JSONObject before, boolean enabled) {
        new Thread(() -> {
            try {
                JSONObject changed = (JSONObject) Cloud.call(screen.a, PATH + "/me",
                        new JSONObject().put("rank_alerts", enabled), true);
                screen.a.runOnUiThread(() -> showStandings(sheet, items, changed));
            } catch (Exception error) {
                screen.a.runOnUiThread(() -> {
                    Toast.makeText(screen.a, "Couldn't save notification settings.", Toast.LENGTH_SHORT).show();
                    showStandings(sheet, items, before);
                });
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
                screen.a.runOnUiThread(() -> showProfile(sheet, data, ranks ? RANKS : VERSUS));
            } catch (Cloud.HttpError error) {
                unavailable(sheet, error.status == 404 ? "This athlete keeps their progress private." : "Connect to Train to see this profile.");
            } catch (Exception error) {
                unavailable(sheet, "Connect to Train to see this profile.");
            }
        }).start();
    }

    /** One friend's athlete profile: a hero in their tier colour, then head-to-head with you, their sprint, and their ranks. */
    private void showProfile(WorkoutViews.Sheet sheet, JSONObject data, int tab) {
        if (!sheet.dialog.isShowing()) return;
        sheet.body.removeAllViews();
        sheet.body.addView(WorkoutFriendViews.athleteHero(ui, data), WorkoutViews.gap(ui, 12));
        sheet.body.addView(WorkoutFriendViews.tabs(ui, TABS, tab, next -> showProfile(sheet, data, next)), WorkoutViews.gap(ui, 12));
        if (tab == RANKS) showRanks(sheet, data.optJSONObject("ranks"));
        else if (tab == SPRINT) showSprint(sheet, data);
        else for (View part : WorkoutFriendViews.versus(ui, data, screen.overview())) sheet.body.addView(part, WorkoutViews.gap(ui, 10));
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
