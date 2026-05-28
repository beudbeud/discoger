import re
import logging
import discogs_client


class DiscogerInfo:
    def __init__(self, url, d, release_id):
        self.url = url
        self.discogs = d

        if len(re.findall(r"\/master\/\d+", self.url)) == 1:
            self.media_type = "master"
        else:
            self.media_type = "release"

        self.release_id = release_id

    @property
    def release_info(self) -> dict:
        try:
            if self.media_type == "master":
                master = self.discogs.master(self.release_id)
                all_info = self.discogs.release(master.main_release.id)
            else:
                all_info = self.discogs.release(self.release_id)
        except discogs_client.exceptions.DiscogsAPIError as e:
            logging.error("Error fetching release %s: %s" % (self.release_id, e))
            raise

        return {
            "release_id": self.release_id,
            "artist": all_info.artists[0].name,
            "title": all_info.title,
            "url": self.url,
            "type": self.media_type,
            "image": all_info.images[0]["uri"] if all_info.images else None,
            "last_sell": dict(),
        }
