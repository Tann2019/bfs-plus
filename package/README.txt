BFS PLUS - a community mod for Beat For Speed
=============================================

What you get
------------
* 3D LYRICS IN GAME - song lyrics appear as big signs beside the road, light up as they are sung
  (karaoke), and fade away as you drive past. Works with any chart that has lyrics.
* 3D LYRIC DESIGNER in the chart editor - design those signs yourself: text, colours, fonts, size,
  animations, and where and when each one appears. Ride along with the song to preview.
* Better LYRICS ASSISTANT - stronger local speech recognition to time lyrics, plus "tap to sync".
* ACCESSIBILITY options (Settings > Accessibility mode): bigger text, focus outlines, high contrast,
  reduced motion, a keyboard shortcut list (press ? or F1).

Install
-------
1. Close Beat For Speed.
2. Double-click "Install BFS Plus.bat".
   It finds the game through Steam. The first time, it offers to download MelonLoader (the standard
   open-source Unity mod loader) - say yes, the 3D lyrics need it.
3. Start the game. The first start after installing MelonLoader takes a few extra minutes.

After a game update, run "Install BFS Plus.bat" again (updates can replace the editor files).
To remove everything: "Uninstall BFS Plus.bat" (or Steam > Verify integrity of game files).

Sharing charts
--------------
Charts made with the 3D Lyric Designer work for EVERYONE. Players with BFS Plus see the 3D signs;
players without it see the game's normal on-screen lyrics. Nothing else changes.


HOW TO PUT LYRICS WHERE AND WHEN YOU WANT
=========================================

A) The words and their timing (the normal lyrics)
   1. Open the chart editor from the game and load your song + chart.
   2. Click "Lyrics Assistant". Paste the lyrics (one line per row) and press "Auto-align pasted
      lyrics" - or "Tap to sync": play the song and press Enter / T the moment each line starts.
   3. Fix any line by dragging its block on the lyrics lane under the notes (drag the edges to change
      how long it lasts). This timing is when each line is SUNG.

B) The 3D signs (how they look and where they stand)
   1. Click "3D Lyrics" (next to Lyrics Assistant). The 3D view opens with the designer on the left.
   2. Click "Generate from lyrics" - one sign per lyric line, alternating sides of the road.
   3. Click a sign in the list to edit it:
        Text      - lines, size, colour, bold/italic
        Timing    - "Sung from" / "Sung until" (seconds). "Karaoke/Typewriter starts / ends": when the
                    words light up or type in - empty = follows the singing.
        Placement - "Follow the road": the sign stands beside the road where you will be while the
                    line is sung (Side, Distance, Height, Angle).
                    "Fixed in the world": the sign stays exactly where you put it, with its own
                    "Appears"/"Disappears" times.
        Look      - font, opacity, outline, gradient, reveal (karaoke/typewriter), enter/exit effect
   4. To move a road sign earlier or later along the road: drag it along the road in the 3D view,
      or type the second you drive past it in "Pass it at". A sign placed like this stays exactly
      there (the TimeOffset setting no longer moves it). Clear the field to go back to automatic.
   5. To put a sign ANYWHERE in the world: "+ Place in world...", then click in the 3D view.
      Click a building wall to stick the sign onto it. Then drag it: drag = move, Shift+drag = higher /
      lower, Alt+drag = turn.
   6. Press Play with "Ride along" ticked to watch it like the player will. Pause, adjust, repeat.
      Move through the song with the scrubber bar (or the 5s / 1s buttons), or grab the green time
      tag over the rider and drag it along the road. Time labels on the road show when you are where.
      Untick "Show buildings" if the blocks get in the way.
   7. Save / Import to Game / Upload to Workshop as usual - the signs are saved in the chart.

   Buildings in the 3D view: play a song once in each scene (City, Forest...) with BFS Plus installed;
   the mod records that scene's buildings for the editor.

In-game settings
----------------
UserData\MelonPreferences.cfg, section [BfsLyric3D] (edits apply live within 2 seconds):
  TimeOffset    seconds to move automatic signs later along the road (default 4.5;
                hand-placed signs ignore it)
  LeadSeconds   how early a sign appears down the road (default 8)
  Scale, Opacity, Font, Enter, Exit, Reveal, WallSnap ...
  Enabled = false turns the 3D lyrics off.
