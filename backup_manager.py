#!/usr/bin/env python3
"""
Backup Manager for Voice AI Tools

Handles backup and restore of voice embeddings, samples, and configuration.
Supports local file backups and can be extended for cloud storage.
"""

import os
import json
import shutil
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Optional


class BackupManager:
    """Manages backup and restore operations for voice AI data."""

    def __init__(self, backup_dir: str = "backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)

        # Directories to backup
        self.embeddings_dir = Path("voice_embeddings")
        self.samples_dir = Path("voice_samples")
        self.config_file = Path("custom_voice_config.py")
        self.presets_file = Path("voice_presets.json")
        self.log_file = Path("session_log.json")

    def create_backup(self, name: Optional[str] = None) -> str:
        """Create a backup of all voice data.

        Args:
            name: Optional backup name (defaults to timestamp)

        Returns:
            Path to the created backup zip file
        """
        if name is None:
            name = f"voice_ai_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        backup_path = self.backup_dir / f"{name}.zip"

        # Files/directories to include in backup
        items_to_backup = []

        if self.embeddings_dir.exists():
            items_to_backup.append(self.embeddings_dir)

        if self.samples_dir.exists():
            items_to_backup.append(self.samples_dir)

        if self.config_file.exists():
            items_to_backup.append(self.config_file)

        if self.presets_file.exists():
            items_to_backup.append(self.presets_file)

        if self.log_file.exists():
            items_to_backup.append(self.log_file)

        if not items_to_backup:
            raise ValueError("No data found to backup")

        # Create backup
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for item in items_to_backup:
                if item.is_file():
                    zipf.write(item, item.name)
                elif item.is_dir():
                    for file_path in item.rglob('*'):
                        if file_path.is_file():
                            arcname = file_path.relative_to(item.parent)
                            zipf.write(file_path, arcname)

        # Create backup metadata
        metadata = {
            "name": name,
            "created_at": datetime.now().isoformat(),
            "items_included": [str(item) for item in items_to_backup],
            "size_bytes": backup_path.stat().st_size
        }

        metadata_path = self.backup_dir / f"{name}_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        return str(backup_path)

    def restore_backup(self, backup_path: str) -> dict:
        """Restore from a backup zip file.

        Args:
            backup_path: Path to the backup zip file

        Returns:
            Dictionary with restore results
        """
        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        results = {
            "restored": [],
            "skipped": [],
            "errors": []
        }

        # Create temporary extraction directory
        temp_dir = self.backup_dir / "temp_extract"
        temp_dir.mkdir(exist_ok=True)

        try:
            # Extract backup
            with zipfile.ZipFile(backup_file, 'r') as zipf:
                zipf.extractall(temp_dir)

            # Restore embeddings
            if (temp_dir / "voice_embeddings").exists():
                if self.embeddings_dir.exists():
                    # Backup existing embeddings
                    existing_backup = self.embeddings_dir.with_suffix('.bak')
                    shutil.move(str(self.embeddings_dir), str(existing_backup))
                    results["restored"].append(f"Backed up existing embeddings to {existing_backup}")

                shutil.move(str(temp_dir / "voice_embeddings"), str(self.embeddings_dir))
                results["restored"].append("Restored voice_embeddings")

            # Restore samples
            if (temp_dir / "voice_samples").exists():
                if self.samples_dir.exists():
                    # Backup existing samples
                    existing_backup = self.samples_dir.with_suffix('.bak')
                    shutil.move(str(self.samples_dir), str(existing_backup))
                    results["restored"].append(f"Backed up existing samples to {existing_backup}")

                shutil.move(str(temp_dir / "voice_samples"), str(self.samples_dir))
                results["restored"].append("Restored voice_samples")

            # Restore config
            if (temp_dir / "custom_voice_config.py").exists():
                if self.config_file.exists():
                    existing_backup = self.config_file.with_suffix('.bak')
                    shutil.move(str(self.config_file), str(existing_backup))
                    results["restored"].append(f"Backed up existing config to {existing_backup}")

                shutil.move(str(temp_dir / "custom_voice_config.py"), str(self.config_file))
                results["restored"].append("Restored custom_voice_config.py")

            # Restore presets
            if (temp_dir / "voice_presets.json").exists():
                if self.presets_file.exists():
                    existing_backup = self.presets_file.with_suffix('.bak')
                    shutil.move(str(self.presets_file), str(existing_backup))
                    results["restored"].append(f"Backed up existing presets to {existing_backup}")

                shutil.move(str(temp_dir / "voice_presets.json"), str(self.presets_file))
                results["restored"].append("Restored voice_presets.json")

            # Restore log
            if (temp_dir / "session_log.json").exists():
                if self.log_file.exists():
                    existing_backup = self.log_file.with_suffix('.bak')
                    shutil.move(str(self.log_file), str(existing_backup))
                    results["restored"].append(f"Backed up existing log to {existing_backup}")

                shutil.move(str(temp_dir / "session_log.json"), str(self.log_file))
                results["restored"].append("Restored session_log.json")

        except Exception as e:
            results["errors"].append(f"Restore failed: {str(e)}")
            # Attempt to restore from backups if error occurred
            self._restore_from_backups()

        finally:
            # Clean up temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

        return results

    def _restore_from_backups(self):
        """Restore files from .bak files if restore failed."""
        backup_files = [
            (self.embeddings_dir.with_suffix('.bak'), self.embeddings_dir),
            (self.samples_dir.with_suffix('.bak'), self.samples_dir),
            (self.config_file.with_suffix('.bak'), self.config_file),
            (self.presets_file.with_suffix('.bak'), self.presets_file),
            (self.log_file.with_suffix('.bak'), self.log_file),
        ]

        for backup_file, original_file in backup_files:
            if backup_file.exists():
                if original_file.exists():
                    shutil.rmtree(str(original_file)) if original_file.is_dir() else original_file.unlink()
                shutil.move(str(backup_file), str(original_file))

    def list_backups(self) -> list:
        """List all available backups.

        Returns:
            List of backup information dictionaries
        """
        backups = []
        for backup_file in self.backup_dir.glob("*.zip"):
            metadata_file = backup_file.with_suffix('').with_suffix('_metadata.json')
            metadata = {
                "name": backup_file.stem,
                "path": str(backup_file),
                "size_bytes": backup_file.stat().st_size,
                "created_at": datetime.fromtimestamp(backup_file.stat().st_mtime).isoformat()
            }

            if metadata_file.exists():
                try:
                    with open(metadata_file) as f:
                        metadata.update(json.load(f))
                except Exception:
                    pass

            backups.append(metadata)

        return sorted(backups, key=lambda x: x["created_at"], reverse=True)

    def delete_backup(self, backup_name: str) -> bool:
        """Delete a backup.

        Args:
            backup_name: Name of the backup to delete (without .zip extension)

        Returns:
            True if deleted, False if not found
        """
        backup_file = self.backup_dir / f"{backup_name}.zip"
        metadata_file = self.backup_dir / f"{backup_name}_metadata.json"

        deleted = False
        if backup_file.exists():
            backup_file.unlink()
            deleted = True

        if metadata_file.exists():
            metadata_file.unlink()

        return deleted

    def auto_backup(self, max_backups: int = 10) -> str:
        """Create automatic backup and cleanup old backups.

        Args:
            max_backups: Maximum number of backups to keep

        Returns:
            Path to the created backup
        """
        # Create new backup
        backup_path = self.create_backup()

        # Cleanup old backups
        backups = self.list_backups()
        while len(backups) > max_backups:
            oldest_backup = backups[-1]
            self.delete_backup(oldest_backup["name"])
            backups.pop()

        return backup_path


def main():
    """CLI interface for backup operations."""
    import sys

    manager = BackupManager()

    if len(sys.argv) < 2:
        print("Usage: python backup_manager.py [create|restore|list|delete|auto] [args]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "create":
        name = sys.argv[2] if len(sys.argv) > 2 else None
        backup_path = manager.create_backup(name)
        print(f"Backup created: {backup_path}")

    elif command == "restore":
        if len(sys.argv) < 3:
            print("Usage: python backup_manager.py restore <backup_path>")
            sys.exit(1)
        backup_path = sys.argv[2]
        results = manager.restore_backup(backup_path)
        print("Restore results:")
        print(f"  Restored: {results['restored']}")
        print(f"  Skipped: {results['skipped']}")
        if results['errors']:
            print(f"  Errors: {results['errors']}")

    elif command == "list":
        backups = manager.list_backups()
        print("Available backups:")
        for backup in backups:
            print(f"  {backup['name']} ({backup['size_bytes']} bytes) - {backup['created_at']}")

    elif command == "delete":
        if len(sys.argv) < 3:
            print("Usage: python backup_manager.py delete <backup_name>")
            sys.exit(1)
        backup_name = sys.argv[2]
        if manager.delete_backup(backup_name):
            print(f"Backup deleted: {backup_name}")
        else:
            print(f"Backup not found: {backup_name}")

    elif command == "auto":
        max_backups = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        backup_path = manager.auto_backup(max_backups)
        print(f"Automatic backup created: {backup_path}")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()