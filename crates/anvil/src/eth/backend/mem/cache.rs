use crate::config::anvil_tmp_dir;
use alloy_primitives::B256;
use foundry_evm::backend::StateSnapshot;
use rmp_serde::encode;
use serde::Serialize;
use std::fs::File;
use std::io::BufReader;
use std::{
    io,
    path::{Path, PathBuf},
};
use tokio::io::AsyncWriteExt;

/// On disk state cache
///
/// A basic tempdir which stores states on disk
pub struct DiskStateCache {
    /// The path where to create the tempdir in
    pub(crate) temp_path: Option<PathBuf>,
}

#[derive(Debug, thiserror::Error)]
pub enum CacheError {
    /// Provides additional path context for [`fs::write`].
    #[error("failed to write to {path:?}: {source}")]
    Compress { source: lz4_flex::frame::Error, path: PathBuf },
    /// Provides additional path context for [`fs::write`].
    #[error("failed to write to {path:?}: {source}")]
    Write { source: io::Error, path: PathBuf },
    /// Provides additional path context for [`File::create`].
    #[error("failed to create file {path:?}: {source}")]
    Create { source: io::Error, path: PathBuf },
    /// Provides additional path context for [`File::open`].
    #[error("failed to open file {path:?}: {source}")]
    Read { source: io::Error, path: PathBuf },
    /// Provides additional path context for the file whose contents should be parsed as JSON.
    #[error("failed to write rmp file: {path:?}: {source}")]
    WriteSerde { source: rmp_serde::encode::Error, path: PathBuf },
    /// Provides additional path context for the file whose contents should be parsed as JSON.
    #[error("failed to read rmp file: {path:?}: {source}")]
    ReadSerde { source: rmp_serde::decode::Error, path: PathBuf },
}

/// Writes the object as a JSON object.
pub async fn write_cache_file<T: Serialize>(
    path: &Path,
    obj: &T,
) -> std::result::Result<(), CacheError> {
    let file = tokio::fs::File::create(path)
        .await
        .map_err(|err| CacheError::Create { source: err, path: path.into() })?;
    let mut file = tokio::io::BufWriter::new(file);
    let mut buf = Vec::new();
    let mut wtr = lz4_flex::frame::FrameEncoder::new(&mut buf);
    if let Err(err) = encode::write(&mut wtr, obj) {
        return Err(CacheError::WriteSerde { source: err.into(), path: path.into() });
    }
    wtr.finish().map_err(|err| CacheError::Compress { source: err, path: path.into() })?;
    file.write_all(&buf)
        .await
        .map_err(|err| CacheError::Write { source: err, path: path.into() })?;
    Ok(())
}

/// Reads the object from a JSON file.
pub fn read_cache_file<T: serde::de::DeserializeOwned>(
    path: &Path,
) -> std::result::Result<T, CacheError> {
    let file =
        File::open(path).map_err(|err| CacheError::Read { source: err, path: path.into() })?;
    let file = BufReader::new(file);
    let mut rdr = lz4_flex::frame::FrameDecoder::new(file);
    let obj = rmp_serde::from_read(&mut rdr)
        .map_err(|err| CacheError::ReadSerde { source: err, path: path.into() })?;
    Ok(obj)
}

impl DiskStateCache {
    /// Specify the path where to create the tempdir in
    pub fn with_path(self, temp_path: PathBuf) -> Self {
        Self { temp_path: Some(temp_path) }
    }
    /// Returns the cache file for the given hash
    fn with_cache_file<F, R>(&mut self, hash: B256, f: F) -> Option<R>
    where
        F: FnOnce(PathBuf) -> R,
    {
        if let Some(temp_dir) = &self.temp_path {
            let path = temp_dir.as_path().join(format!("{hash:?}.json"));
            Some(f(path))
        } else {
            None
        }
    }

    /// Stores the snapshot for the given hash
    ///
    /// Note: this writes the state on a new spawned task
    ///
    /// Caution: this requires a running tokio Runtime.
    pub fn write(&mut self, hash: B256, state: StateSnapshot) {
        self.with_cache_file(hash, |file| {
            tokio::task::spawn(async move {
                match write_cache_file(&file, &state).await {
                    Ok(_) => {
                        trace!(target: "backend", ?hash, "wrote state json file");
                    }
                    Err(err) => {
                        error!(target: "backend", %err, ?hash, "Failed to load state snapshot");
                    }
                };
            });
        });
    }

    /// Loads the snapshot file for the given hash
    ///
    /// Returns None if it doesn't exist or deserialization failed
    pub fn read(&mut self, hash: B256) -> Option<StateSnapshot> {
        self.with_cache_file(hash, |file| match read_cache_file::<StateSnapshot>(&file) {
            Ok(state) => {
                trace!(target: "backend", ?hash,"loaded cached state");
                Some(state)
            }
            Err(err) => {
                error!(target: "backend", %err, ?hash, "Failed to load state snapshot");
                None
            }
        })
        .flatten()
    }

    /// Removes the cache file for the given hash, if it exists
    pub fn remove(&mut self, hash: B256) {
        self.with_cache_file(hash, |file| {
            foundry_common::fs::remove_file(file).map_err(|err| {
                error!(target: "backend", %err, %hash, "Failed to remove state snapshot");
            })
        });
    }
}

impl Default for DiskStateCache {
    fn default() -> Self {
        Self { temp_path: anvil_tmp_dir() }
    }
}
