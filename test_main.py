from tea_agent.main_db_gui import main

if __name__ == "__main__":
    from argparse import ArgumentParser
    import logging
    ap = ArgumentParser()
    ap.add_argument("--debug", action="store_true", help="Debug mode.")
    ap.add_argument("--no-gui", action="store_true", help="No GUI mode.")
    args = ap.parse_args()
    if args.debug:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(message)s',
        )
    else:
        from pathlib import Path
        log_fname = Path.home() / ".tea_agent" / "tea_agent.log"
        logging.basicConfig(
            level=logging.WARNING, 
            filemode='w', 
            filename=log_fname,
            format='%(asctime)s %(levelname)s %(filename)s:%(lineno)s %(message)s',
        )
    logging.info("-----> Starting Tea Agent")
    main(debug=args.debug, no_gui=args.no_gui)
