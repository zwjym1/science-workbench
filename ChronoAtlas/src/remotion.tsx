import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {HexiFilm, defaultFilm} from './film';
export const Root = ()=><Composition id="HexiCorridor" component={HexiFilm} width={1280} height={720} fps={30} durationInFrames={900} defaultProps={defaultFilm}/>;
registerRoot(Root);
