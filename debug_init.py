"""Debug script to catch exact error in TkGUI init."""
import traceback, sys
sys.path.insert(0, "/home/sunkw/work/git/tea_agent")
try:
    from tea_agent.gui import main
    main()
except Exception:
    tb = traceback.format_exc()
    print(tb, file=sys.stderr)
    # Also write to file
    with open("/tmp/gui_full_tb.txt", "w") as f:
        f.write(tb)
    print("FULL TRACEBACK WRITTEN TO /tmp/gui_full_tb.txt", file=sys.stderr)
    sys.exit(1)
